"""
Manual Ingester
================

Ingests PDF and Markdown technical manuals using LLM reasoning for intelligent parsing.
Extracted content is indexed into the TechnicalKnowledgeBase for semantic retrieval.

This module enables ARVIS to ingest new equipment manuals and make their content
queryable through the existing RAG infrastructure.

ARCHITECTURE:
- Uses PyPDF2/pymupdf for PDF text extraction (no external dependencies)
- Uses ARVIS UnifiedLLM for reasoning-based tree structure generation
- Indexes into TechnicalKnowledgeBase (ChromaDB)
"""

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

# PDF extraction libraries
try:
    import pdfplumber
    PDF_PARSER = "pdfplumber"
except ImportError:
    try:
        import pymupdf
        PDF_PARSER = "pymupdf"
    except ImportError:
        import PyPDF2
        PDF_PARSER = "PyPDF2"

# ARVIS UnifiedLLM
from agent_unified.llm import UnifiedLLM
from agent_advisory.knowledge_base import TechnicalKnowledgeBase
from agent_advisory.hybrid_rag import TreeKnowledgeBase

logger = logging.getLogger("arvis.advisory.ingester")


@dataclass
class IngestionResult:
    """Result of a document ingestion operation."""
    source_file: str
    doc_name: str
    doc_description: str
    nodes_indexed: int
    total_tokens_estimated: int
    ingestion_time_seconds: float
    equipment_id: Optional[str] = None
    tree_structure: Optional[List[Dict]] = field(default=None, repr=False)
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_file": self.source_file,
            "doc_name": self.doc_name,
            "doc_description": self.doc_description,
            "nodes_indexed": self.nodes_indexed,
            "total_tokens_estimated": self.total_tokens_estimated,
            "ingestion_time_seconds": round(self.ingestion_time_seconds, 2),
            "equipment_id": self.equipment_id,
            "errors": self.errors,
            "status": "success" if not self.errors else "partial"
        }


class ManualIngester:
    """
    Ingests technical manuals (PDF/Markdown) into the TechnicalKnowledgeBase.
    
    Uses LLM reasoning to parse documents into hierarchical tree structures,
    then indexes each node as a searchable snippet in ChromaDB.
    
    Example:
        >>> kb = TechnicalKnowledgeBase()
        >>> ingester = ManualIngester(kb)
        >>> result = await ingester.ingest_pdf("manuals/chiller_specs.pdf", equipment_id="CH-01")
        >>> print(f"Indexed {result.nodes_indexed} sections from {result.doc_name}")
    """
    
    def __init__(
        self,
        knowledge_base: TechnicalKnowledgeBase,
        tree_knowledge_base: Optional[TreeKnowledgeBase] = None,
        max_pages_per_chunk: int = 5,
        max_tokens_per_node: int = 15000
    ):
        """
        Initialize the ManualIngester.
        
        Args:
            knowledge_base: The TechnicalKnowledgeBase instance to index into.
            max_pages_per_chunk: Maximum pages to process in one LLM call.
            max_tokens_per_node: Maximum tokens per tree node.
        """
        self.kb = knowledge_base
        self.tree_kb = tree_knowledge_base
        self.max_pages_per_chunk = max_pages_per_chunk
        self.max_tokens_per_node = max_tokens_per_node
        self.llm = UnifiedLLM()
        logger.info(f"ManualIngester initialized (PDF parser: {PDF_PARSER})")

    async def ingest_pdf(
        self,
        pdf_path: str,
        equipment_id: Optional[str] = None,
        include_tree_in_result: bool = False
    ) -> IngestionResult:
        """
        Ingest a PDF manual into the knowledge base.
        
        Uses LLM reasoning to parse the PDF into a hierarchical tree,
        and indexes each node into ChromaDB.
        
        Args:
            pdf_path: Path to the PDF file.
            equipment_id: Optional equipment ID to tag all snippets with.
            include_tree_in_result: If True, include the full tree structure in the result.
            
        Returns:
            IngestionResult with details about the ingestion.
        """
        start_time = datetime.now()
        pdf_path = Path(pdf_path)
        
        # Validate input
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        if not pdf_path.suffix.lower() == ".pdf":
            raise ValueError(f"File is not a PDF: {pdf_path}")
        
        logger.info(f"Starting PDF ingestion: {pdf_path}")
        print(f"[ManualIngester] Extracting text from PDF: {pdf_path.name}")
        
        # 1. Extract text from PDF
        pages = self._extract_pdf_pages(str(pdf_path))
        print(f"[ManualIngester] Extracted {len(pages)} pages using {PDF_PARSER}")
        
        # 2. Generate document description
        doc_name = pdf_path.stem
        doc_description = await self._generate_doc_description(pages[:3], doc_name)
        print(f"[ManualIngester] Document: {doc_name}")
        print(f"[ManualIngester] Description: {doc_description[:100]}...")
        
        # 3. Build hierarchical tree using LLM reasoning
        print(f"[ManualIngester] Building document tree structure...")
        tree_structure = await self._build_tree_structure(pages, doc_name)
        print(f"[ManualIngester] Generated {len(tree_structure)} top-level sections")
        
        # 4. Flatten tree and index nodes
        nodes = self._flatten_tree(tree_structure)
        errors = []
        total_tokens = 0
        
        print(f"[ManualIngester] Indexing {len(nodes)} nodes into knowledge base...")
        for i, node in enumerate(nodes):
            try:
                # Populate text content from pages
                start_idx = node.get("start_index", 1)
                end_idx = node.get("end_index", len(pages))
                # Bounds check
                start_idx = max(1, start_idx)
                end_idx = min(len(pages), end_idx)
                
                # Extract text describing this node's page range
                node_tables = []
                if 1 <= start_idx <= len(pages):
                    chunk_pages = pages[start_idx-1 : end_idx]
                    
                    # chunk_pages is list of (text, tokens, tables)
                    node_text = "\n\n".join([p[0] for p in chunk_pages])
                    node["text"] = node_text
                    
                    # Aggregate tables
                    for p in chunk_pages:
                        if len(p) >= 3:
                            node_tables.extend(p[2])
                
                content = self._format_node_for_indexing(node, doc_name)
                
                # DEBUG: Verify content before indexing


                total_tokens += len(content.split()) * 1.3  # Rough token estimate
                
                tags = [doc_name]
                if doc_description:
                    tags.append(doc_description[:100])
                
                # Serialize tables to JSON
                extra_meta = {
                    "page_start": start_idx,
                    "page_end": end_idx,
                    "has_table": bool(node_tables)
                }
                if node_tables:
                    extra_meta["table_data_json"] = json.dumps(node_tables)

                if i < 5:
                    print(f"[ManualIngester DEBUG] Indexing Node {i}: Pages {start_idx}-{end_idx}, Table: {bool(node_tables)}, Text Len: {len(node.get('text', ''))}")

                self.kb.index_technical_snippet(
                    content=content,
                    source=str(pdf_path),
                    equipment_id=equipment_id,
                    tags=tags,
                    extra_metadata=extra_meta
                )
                
                if (i + 1) % 10 == 0:
                    print(f"[ManualIngester] Progress: {i+1}/{len(nodes)} nodes indexed")
                
                # Trace telemetry for specific pages (e.g. Page 6)
                if start_idx <= 6 <= end_idx:
                    print(f"[ManualIngester TELEMETRY] Node '{node.get('title')}' covers Page 6. Text Len: {len(node.get('text',''))}, Tables: {len(node_tables)}")

                    
            except Exception as e:
                error_msg = f"Failed to index node '{node.get('title', 'unknown')}': {e}"
                logger.warning(error_msg)
                errors.append(error_msg)

        if self.tree_kb:
            indexed_tree_nodes = self.tree_kb.add_document_tree(
                source=str(pdf_path),
                doc_name=doc_name,
                tree_structure=nodes,
                equipment_id=equipment_id,
            )
            print(f"[ManualIngester] Indexed {indexed_tree_nodes} nodes into tree knowledge base")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        result = IngestionResult(
            source_file=str(pdf_path),
            doc_name=doc_name,
            doc_description=doc_description,
            nodes_indexed=len(nodes) - len(errors),
            total_tokens_estimated=int(total_tokens),
            ingestion_time_seconds=elapsed,
            equipment_id=equipment_id,
            tree_structure=tree_structure if include_tree_in_result else None,
            errors=errors
        )
        
        print(f"[ManualIngester] ✅ Ingestion complete: {result.nodes_indexed} nodes in {elapsed:.1f}s")
        logger.info(f"PDF ingestion complete: {result.nodes_indexed} nodes indexed in {elapsed:.2f}s")
        return result

    def _extract_pdf_pages(self, pdf_path: str) -> List[Tuple[str, int]]:
        """
        Extract text from each page of a PDF.
        
        Returns:
            List of (page_text, token_count, tables_data) tuples.
        """
        pages = []
        
        if PDF_PARSER == "pdfplumber":
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text() or ""
                    page_parts = [page_text]
                    tables_data = []
                    
                    # Extract tables with pdfplumber (superior to pymupdf)
                    tables = page.extract_tables()
                    if tables:
                        print(f"[ManualIngester DEBUG] Page {i+1}: Found {len(tables)} tables")
                        page_parts.append("\n\n[EXTRACTED TABLE DATA]\n")
                        
                        for table in tables:
                            # Filter out empty tables
                            if not table or not any(row for row in table):
                                continue
                                
                            # Conversion to Markdown
                            clean_rows = []
                            for row in table:
                                # Clean: replace None with "", strip newlines
                                clean_row = [str(cell).replace('\n', ' ').strip() if cell is not None else "" for cell in row]
                                # Filter empty rows
                                if any(clean_row):
                                    clean_rows.append(clean_row)
                            
                            if clean_rows:
                                print(f"[ManualIngester DEBUG] Page {i+1}: Table accepted with {len(clean_rows)} rows. Header: {clean_rows[0][:3]}")
                                table_str = ""
                                # Start Table Block with Metadata
                                table_str += f'\n\n<table_data page="{i+1}" source="{Path(pdf_path).name}">\n'
                                
                                # Header
                                headers = clean_rows[0]
                                table_str += "| " + " | ".join(headers) + " |\n"
                                table_str += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                # Body
                                for row in clean_rows[1:]:
                                    table_str += "| " + " | ".join(row) + " |\n"
                                
                                # End Table Block
                                table_str += "</table_data>\n"
                                page_parts.append(table_str)
                                
                                # Store structured data
                                tables_data.append({
                                    "page": i+1,
                                    "source": Path(pdf_path).name,
                                    "headers": headers,
                                    "rows": clean_rows[1:]
                                })
                    
                    final_text = "".join(page_parts)
                    token_count = len(final_text.split()) * 1.3
                    pages.append((final_text, int(token_count), tables_data))
                    
        elif PDF_PARSER == "pymupdf":
            import pymupdf
            doc = pymupdf.open(pdf_path)
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                tables_data = []
                
                # Attempt table extraction
                try:
                    tabs = page.find_tables()
                    if tabs.tables:
                        text += "\n\n[EXTRACTED TABLE DATA]\n"
                        for i, table in enumerate(tabs):
                            extracted = table.extract()
                            if not extracted: continue
                            
                            if len(extracted) > 0:
                                clean_rows = []
                                for row in extracted:
                                    clean_row = [str(cell).replace('\n', ' ').strip() if cell is not None else "" for cell in row]
                                    clean_rows.append(clean_row)
                                
                                headers = clean_rows[0]
                                text += "| " + " | ".join(headers) + " |\n"
                                text += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                                for row in clean_rows[1:]:
                                    text += "| " + " | ".join(row) + " |\n"
                                text += "\n"
                except Exception as e:
                    logger.warning(f"Table extraction failed on page {page_num}: {e}")

                token_count = len(text.split()) * 1.3  # Rough estimate
                pages.append((text, int(token_count), tables_data))
            doc.close()
            
        else:
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text = page.extract_text() or ""
                    token_count = len(text.split()) * 1.3
                    pages.append((text, int(token_count), []))
        
        return pages

    async def _generate_doc_description(self, first_pages: List[Tuple[str, int]], doc_name: str) -> str:
        """Generate a brief description of the document using LLM."""
        combined_text = "\n\n".join([p[0][:2000] for p in first_pages[:3]])
        
        prompt = f"""Based on the following excerpt from a technical document titled "{doc_name}", 
provide a brief 1-2 sentence description of what this document covers.

Document excerpt:
{combined_text[:4000]}

Provide ONLY the description, no preamble."""

        try:
            response = await self.llm.ask([{"role": "user", "content": prompt}])
            return response.content.strip() if response.content else f"Technical manual: {doc_name}"
        except Exception as e:
            logger.warning(f"Failed to generate description: {e}")
            return f"Technical manual: {doc_name}"

    async def _build_tree_structure(self, pages: List[Tuple[str, int]], doc_name: str) -> List[Dict]:
        """
        Build a hierarchical tree structure from PDF pages using LLM reasoning.
        
        This is the core intelligence - the LLM analyzes the document and creates
        a table-of-contents-like structure with page references.
        """
        # Process pages in chunks to stay within context limits
        all_sections = []
        chunk_size = self.max_pages_per_chunk
        
        for chunk_start in range(0, len(pages), chunk_size):
            chunk_end = min(chunk_start + chunk_size, len(pages))
            chunk_pages = pages[chunk_start:chunk_end]
            
            # Build page content with labels
            page_content = ""
            for i, (text, _, _) in enumerate(chunk_pages):
                page_num = chunk_start + i + 1
                # Truncate each page to avoid context overflow
                truncated = text[:3000] if len(text) > 3000 else text
                page_content += f"\n<PAGE {page_num}>\n{truncated}\n</PAGE {page_num}>\n"
            
            # Ask LLM to identify sections in this chunk
            prompt = f"""Analyze the following pages from a technical manual and identify the main sections/chapters.

For each section found, provide:
1. title: The section title
2. start_page: The page number where it starts
3. summary: A brief 1-2 sentence description of the section content
4. models_covered: A JSON array of all specific model IDs mentioned in this section (e.g., ["0312P", "1002"]).

HINT: If the section contains performance tables, capacities (kW), COPs, or electrical data, make sure the summary includes keywords like "cooling capacity", "COP", "EER", "heating capacity", or "nominal performance". This is critical for search ranking.

Return a JSON array of sections. Example format:
[
  {{"title": "Installation Requirements", "start_page": 5, "summary": "Covers electrical and plumbing requirements for installation.", "models_covered": []}},
  {{"title": "Performance Data 30XW-P", "start_page": 10, "summary": "Technical specs for high efficiency units.", "models_covered": ["0312P", "0502P", "1002P"]}}
]

Document: {doc_name}
Pages {chunk_start + 1} to {chunk_end}:
{page_content}

HINT: If you see a list of model numbers (e.g., 4-digit codes like 0312, 1002) in the section, include them in the 'models_covered' field.

Return ONLY the JSON array, no other text."""

            try:
                sections = await self.llm.ask_json([{"role": "user", "content": prompt}])
                if isinstance(sections, list):
                    all_sections.extend(sections)
            except Exception as e:
                logger.warning(f"Failed to parse chunk {chunk_start}-{chunk_end}: {e}")
                # Fallback: create a single section for this chunk
                all_sections.append({
                    "title": f"Section (Pages {chunk_start + 1}-{chunk_end})",
                    "start_page": chunk_start + 1,
                    "summary": "Content extracted from document."
                })
        
        # Post-process: deduplicate and assign end pages
        return self._finalize_tree_structure(all_sections, len(pages))

    def _finalize_tree_structure(self, sections: List[Dict], total_pages: int) -> List[Dict]:
        """Clean up and finalize the tree structure."""
        if not sections:
            return [{
                "title": "Document Content",
                "start_index": 1,
                "end_index": total_pages,
                "summary": "Full document content."
            }]
        
        # Sort by start page
        sections = sorted(sections, key=lambda x: x.get("start_page", 1))
        
        # Deduplicate by title (keep first occurrence)
        seen_titles = set()
        unique_sections = []
        for s in sections:
            title = s.get("title", "").strip().lower()
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_sections.append(s)
        
        # Assign node IDs and end pages
        result = []
        for i, section in enumerate(unique_sections):
            start_page = section.get("start_page", 1)
            
            # End page is either the start of next section - 1, or total pages
            if i + 1 < len(unique_sections):
                end_page = unique_sections[i + 1].get("start_page", total_pages) - 1
            else:
                end_page = total_pages
            
            result.append({
                "title": section.get("title", f"Section {i + 1}"),
                "node_id": str(i + 1).zfill(4),
                "start_index": start_page,
                "end_index": max(end_page, start_page),
                "summary": section.get("summary", "")
            })
        
        return result

    def _flatten_tree(self, nodes: List[Dict], parent_path: str = "") -> List[Dict]:
        """
        Recursively flatten a tree structure into a list of nodes.
        """
        result = []
        for node in nodes:
            title = node.get("title", "Untitled")
            current_path = f"{parent_path} > {title}" if parent_path else title
            
            flat_node = {
                "title": title,
                "node_id": node.get("node_id"),
                "hierarchy_path": current_path,
                "summary": node.get("summary"),
                "text": node.get("text"),
                "start_index": node.get("start_index"),
                "end_index": node.get("end_index"),
            }
            result.append(flat_node)
            
            if "nodes" in node and node["nodes"]:
                result.extend(self._flatten_tree(node["nodes"], current_path))
        
        return result

    def _extract_model_ids(self, text: str) -> List[str]:
        """Extract model IDs from text using universal HVAC patterns."""
        from agent_advisory.equipment_patterns import extract_model_ids
        return extract_model_ids(text)

    def _format_node_for_indexing(self, node: Dict, doc_name: str) -> str:
        """Format a tree node into a content string for indexing."""
        title = node.get("title", "Untitled")
        # High-priority block for vector embedding
        summary = node.get("summary", "")
        
        # Auto-detect models if not explicitly provided
        models = node.get("models_covered", [])
        if not models and node.get("text"):
            models = self._extract_model_ids(node["text"])
            
        model_str = ", ".join(models) if models else "General"

        # Extract table column headers as searchable keywords
        # This boosts retrieval ranking for performance data queries
        table_keywords = set()
        if node.get("tables"):
            for table in node["tables"]:
                for header in table.get("headers", []):
                    if header and len(header) > 2:
                        table_keywords.add(header.strip())
        keyword_str = ", ".join(sorted(table_keywords)) if table_keywords else ""

        lines = [
            f"SECTION: {title}",
            f"SUMMARY: {summary}",
            f"MODELS: {model_str}",
            f"SOURCE: {doc_name}",
        ]
        if keyword_str:
            lines.append(f"TABLE COLUMNS: {keyword_str}")
        lines.append("")
        
        start_page = node.get("start_index")
        end_page = node.get("end_index")
        if start_page and end_page:
            lines.append(f"📄 Pages {start_page}-{end_page}")
        
        if node.get("text"):
            text = node["text"]
            # Include text but cap it to keep embedding focused
            if len(text) > 5000:
                 lines.append(text[:5000] + "\n...[truncated for indexing]...")
            else:
                 lines.append(text)
        
        return "\n".join(lines)

    async def ingest_markdown(
        self,
        md_path: str,
        equipment_id: Optional[str] = None,
        include_tree_in_result: bool = False
    ) -> IngestionResult:
        """
        Ingest a Markdown manual into the knowledge base.
        
        Parses headers to build a tree, then indexes each section.
        """
        start_time = datetime.now()
        md_path = Path(md_path)
        
        if not md_path.exists():
            raise FileNotFoundError(f"Markdown file not found: {md_path}")
        if md_path.suffix.lower() not in [".md", ".markdown"]:
            raise ValueError(f"File is not a Markdown file: {md_path}")
        
        logger.info(f"Starting Markdown ingestion: {md_path}")
        
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse headers into tree
        tree_structure = self._parse_markdown_headers(content)
        doc_name = md_path.stem
        doc_description = f"Markdown documentation: {doc_name}"
        
        # Flatten and index
        nodes = self._flatten_tree(tree_structure)
        if self.tree_kb:
            self.tree_kb.add_document_tree(
                source=str(md_path),
                doc_name=doc_name,
                tree_structure=tree_structure,
                equipment_id=equipment_id,
            )
        errors = []
        total_tokens = 0
        
        for node in nodes:
            try:
                formatted = self._format_node_for_indexing(node, doc_name)
                total_tokens += len(formatted.split()) * 1.3
                
                self.kb.index_technical_snippet(
                    content=formatted,
                    source=str(md_path),
                    equipment_id=equipment_id,
                    tags=[doc_name]
                )
            except Exception as e:
                errors.append(f"Failed to index '{node.get('title')}': {e}")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        
        return IngestionResult(
            source_file=str(md_path),
            doc_name=doc_name,
            doc_description=doc_description,
            nodes_indexed=len(nodes) - len(errors),
            total_tokens_estimated=int(total_tokens),
            ingestion_time_seconds=elapsed,
            equipment_id=equipment_id,
            tree_structure=tree_structure if include_tree_in_result else None,
            errors=errors
        )

    def _parse_markdown_headers(self, content: str) -> List[Dict]:
        """Parse markdown headers into a flat list of sections."""
        header_pattern = r'^(#{1,6})\s+(.+)$'
        lines = content.split('\n')
        
        sections = []
        current_text = []
        current_header = None
        
        for line_num, line in enumerate(lines, 1):
            match = re.match(header_pattern, line.strip())
            if match:
                # Save previous section
                if current_header:
                    sections.append({
                        "title": current_header["title"],
                        "node_id": str(len(sections) + 1).zfill(4),
                        "level": current_header["level"],
                        "line_num": current_header["line_num"],
                        "text": "\n".join(current_text).strip(),
                        "summary": "\n".join(current_text[:3]).strip()[:200]
                    })
                
                current_header = {
                    "title": match.group(2).strip(),
                    "level": len(match.group(1)),
                    "line_num": line_num
                }
                current_text = []
            else:
                current_text.append(line)
        
        # Don't forget the last section
        if current_header:
            sections.append({
                "title": current_header["title"],
                "node_id": str(len(sections) + 1).zfill(4),
                "level": current_header["level"],
                "line_num": current_header["line_num"],
                "text": "\n".join(current_text).strip(),
                "summary": "\n".join(current_text[:3]).strip()[:200]
            })
        
        return sections


# Convenience function for CLI usage
async def ingest_document(
    file_path: str,
    equipment_id: Optional[str] = None,
    persist_directory: str = "data/knowledge_base"
) -> IngestionResult:
    """
    Convenience function to ingest a single document.
    """
    kb = TechnicalKnowledgeBase(persist_directory=persist_directory)
    ingester = ManualIngester(kb)
    
    file_path = Path(file_path)
    if file_path.suffix.lower() == ".pdf":
        return await ingester.ingest_pdf(str(file_path), equipment_id=equipment_id)
    elif file_path.suffix.lower() in [".md", ".markdown"]:
        return await ingester.ingest_markdown(str(file_path), equipment_id=equipment_id)
    else:
        raise ValueError(f"Unsupported file type: {file_path.suffix}")


if __name__ == "__main__":
    import argparse
    
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")
    
    parser = argparse.ArgumentParser(description="Ingest a PDF or Markdown manual into ARVIS Knowledge Base")
    parser.add_argument("file_path", help="Path to the PDF or Markdown file")
    parser.add_argument("--equipment-id", "-e", help="Equipment ID to tag the content with")
    parser.add_argument("--persist-dir", "-d", default="data/knowledge_base", help="ChromaDB persist directory")
    
    args = parser.parse_args()
    
    result = asyncio.run(ingest_document(
        args.file_path,
        equipment_id=args.equipment_id,
        persist_directory=args.persist_dir
    ))
    
    print("\n" + "=" * 60)
    print("INGESTION COMPLETE")
    print("=" * 60)
    print(f"Document: {result.doc_name}")
    print(f"Description: {result.doc_description[:200]}..." if len(result.doc_description) > 200 else f"Description: {result.doc_description}")
    print(f"Nodes Indexed: {result.nodes_indexed}")
    print(f"Estimated Tokens: {result.total_tokens_estimated}")
    print(f"Time: {result.ingestion_time_seconds:.2f}s")
    if result.errors:
        print(f"Errors: {len(result.errors)}")
        for err in result.errors[:5]:
            print(f"  - {err}")
