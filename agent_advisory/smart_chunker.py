"""
Smart Chunker for ARVIS RAG
============================

Advanced content chunking that splits documents by content type:
- Tables (parameter blocks, specifications)
- Procedures (numbered steps)
- Limits/Setpoints (operational parameters)
- Control descriptions

This produces finer-grained chunks for better retrieval on procedural questions.
"""

import re
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from enum import Enum


class ChunkType(Enum):
    """Types of content chunks."""
    SECTION = "section"           # General section header
    TABLE = "table"               # Tabular data
    PROCEDURE = "procedure"       # Numbered steps
    PARAMETERS = "parameters"     # Limits, setpoints, ranges
    SPECIFICATIONS = "specifications"  # Equipment specs
    SAFETY = "safety"             # Safety warnings
    NARRATIVE = "narrative"       # General text


@dataclass
class ContentChunk:
    """A chunk of content with type metadata."""
    chunk_type: ChunkType
    title: str
    content: str
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    parent_section: Optional[str] = None
    
    @property
    def token_estimate(self) -> int:
        """Rough token count estimate."""
        return int(len(self.content.split()) * 1.3)
    
    def to_dict(self) -> Dict:
        return {
            "chunk_type": self.chunk_type.value,
            "title": self.title,
            "content": self.content,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "parent_section": self.parent_section,
            "token_estimate": self.token_estimate,
        }


class SmartChunker:
    """
    Chunks document content by type for optimal retrieval.
    
    Instead of coarse section-level chunks, this produces:
    - Individual tables as chunks
    - Individual procedures as chunks
    - Parameter blocks as chunks
    """
    
    # Patterns for detecting content types
    PATTERNS = {
        # Tables: Markdown-style or pipe-delimited
        "table": r"(?:(?:\|[^\n]+\|\n)+)|(?:(?:[^\n]+\t[^\n]+\n)+)",
        
        # Procedures: Numbered steps
        "procedure": r"(?:(?:^|\n)\s*\d+[\.\)]\s+.+(?:\n(?!\s*\d+[\.\)])[^\n]+)*)+",
        
        # Parameters: key: value or key = value with numbers
        "parameters": r"(?:(?:^|\n)\s*[\w\s]+[:=]\s*[\d\.\-]+\s*[\w°/%]*)+",
        
        # Safety warnings
        "safety": r"(?:⚠️|WARNING|CAUTION|DANGER|NOTE:).*?(?=\n\n|\Z)",
        
        # Limits/ranges
        "limits": r"(?:min(?:imum)?|max(?:imum)?|range|limit).*?[\d\.\-]+",
    }
    
    def __init__(self, max_chunk_tokens: int = 500):
        """
        Initialize the chunker.
        
        Args:
            max_chunk_tokens: Maximum tokens per chunk (will split large chunks)
        """
        self.max_chunk_tokens = max_chunk_tokens
    
    def chunk_section(
        self,
        content: str,
        section_title: str,
        page_start: Optional[int] = None,
        page_end: Optional[int] = None
    ) -> List[ContentChunk]:
        """
        Break a section into typed chunks.
        
        Args:
            content: The section content
            section_title: Title of the parent section
            page_start: Starting page number
            page_end: Ending page number
            
        Returns:
            List of ContentChunks
        """
        chunks = []
        remaining_content = content
        
        # 1. Extract tables
        tables = self._extract_tables(content)
        for i, table in enumerate(tables):
            chunks.append(ContentChunk(
                chunk_type=ChunkType.TABLE,
                title=f"{section_title} - Table {i+1}",
                content=table,
                page_start=page_start,
                page_end=page_end,
                parent_section=section_title
            ))
            remaining_content = remaining_content.replace(table, "")
        
        # 2. Extract procedures
        procedures = self._extract_procedures(remaining_content)
        for i, proc in enumerate(procedures):
            chunks.append(ContentChunk(
                chunk_type=ChunkType.PROCEDURE,
                title=f"{section_title} - Procedure {i+1}",
                content=proc,
                page_start=page_start,
                page_end=page_end,
                parent_section=section_title
            ))
            remaining_content = remaining_content.replace(proc, "")
        
        # 3. Extract parameter blocks
        params = self._extract_parameters(remaining_content)
        if params:
            chunks.append(ContentChunk(
                chunk_type=ChunkType.PARAMETERS,
                title=f"{section_title} - Parameters",
                content="\n".join(params),
                page_start=page_start,
                page_end=page_end,
                parent_section=section_title
            ))
        
        # 4. Extract safety warnings
        safety = self._extract_safety(remaining_content)
        if safety:
            chunks.append(ContentChunk(
                chunk_type=ChunkType.SAFETY,
                title=f"{section_title} - Safety Notes",
                content="\n".join(safety),
                page_start=page_start,
                page_end=page_end,
                parent_section=section_title
            ))
        
        # 5. Keep remaining content as narrative
        remaining_content = remaining_content.strip()
        if remaining_content and len(remaining_content) > 100:
            # Split into smaller chunks if needed
            narrative_chunks = self._split_narrative(
                remaining_content, section_title, page_start, page_end
            )
            chunks.extend(narrative_chunks)
        
        # If no specialized chunks found, return the whole section
        if not chunks:
            chunks.append(ContentChunk(
                chunk_type=ChunkType.SECTION,
                title=section_title,
                content=content,
                page_start=page_start,
                page_end=page_end,
                parent_section=None
            ))
        
        return chunks
    
    def _extract_tables(self, content: str) -> List[str]:
        """Extract markdown or pipe-delimited tables."""
        tables = []
        
        # Markdown tables (lines with |)
        lines = content.split("\n")
        table_lines = []
        in_table = False
        
        for line in lines:
            if "|" in line and line.strip().startswith("|"):
                in_table = True
                table_lines.append(line)
            elif in_table:
                if line.strip() == "" or not "|" in line:
                    if len(table_lines) > 1:
                        tables.append("\n".join(table_lines))
                    table_lines = []
                    in_table = False
                else:
                    table_lines.append(line)
        
        if table_lines and len(table_lines) > 1:
            tables.append("\n".join(table_lines))
        
        return tables
    
    def _extract_procedures(self, content: str) -> List[str]:
        """Extract numbered procedure steps."""
        procedures = []
        
        # Find blocks of numbered steps
        pattern = r"((?:^|\n)(?:\s*\d+[\.\)]\s+[^\n]+\n?)+)"
        matches = re.findall(pattern, content, re.MULTILINE)
        
        for match in matches:
            # Only keep if it has at least 2 steps
            steps = re.findall(r"\d+[\.\)]", match)
            if len(steps) >= 2:
                procedures.append(match.strip())
        
        return procedures
    
    def _extract_parameters(self, content: str) -> List[str]:
        """Extract parameter definitions (key: value with units)."""
        params = []
        
        # Pattern for "Parameter: Value Unit" style
        pattern = r"([A-Za-z][A-Za-z\s]+)[:=]\s*([\d\.\-]+)\s*([A-Za-z°/%³²]*)"
        matches = re.findall(pattern, content)
        
        for name, value, unit in matches:
            if name.strip() and value.strip():
                params.append(f"{name.strip()}: {value} {unit}".strip())
        
        return params
    
    def _extract_safety(self, content: str) -> List[str]:
        """Extract safety warnings and cautions."""
        safety = []
        
        patterns = [
            r"⚠️[^\n]+",
            r"WARNING[:\s]+[^\n]+",
            r"CAUTION[:\s]+[^\n]+",
            r"DANGER[:\s]+[^\n]+",
            r"NOTE[:\s]+[^\n]+",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            safety.extend(matches)
        
        return safety
    
    def _split_narrative(
        self,
        content: str,
        section_title: str,
        page_start: Optional[int],
        page_end: Optional[int]
    ) -> List[ContentChunk]:
        """Split narrative content into smaller chunks."""
        chunks = []
        
        # Split by paragraphs
        paragraphs = content.split("\n\n")
        current_chunk = []
        current_tokens = 0
        
        for para in paragraphs:
            para_tokens = len(para.split()) * 1.3
            
            if current_tokens + para_tokens > self.max_chunk_tokens and current_chunk:
                # Save current chunk
                chunks.append(ContentChunk(
                    chunk_type=ChunkType.NARRATIVE,
                    title=f"{section_title} - Part {len(chunks)+1}",
                    content="\n\n".join(current_chunk),
                    page_start=page_start,
                    page_end=page_end,
                    parent_section=section_title
                ))
                current_chunk = [para]
                current_tokens = para_tokens
            else:
                current_chunk.append(para)
                current_tokens += para_tokens
        
        # Don't forget the last chunk
        if current_chunk:
            chunks.append(ContentChunk(
                chunk_type=ChunkType.NARRATIVE,
                title=f"{section_title} - Part {len(chunks)+1}",
                content="\n\n".join(current_chunk),
                page_start=page_start,
                page_end=page_end,
                parent_section=section_title
            ))
        
        return chunks
    
    def chunk_document(
        self,
        sections: List[Dict],
        page_contents: Optional[List[str]] = None
    ) -> List[ContentChunk]:
        """
        Chunk an entire document from its section list.
        
        Args:
            sections: List of section dicts with title, content, start_index, end_index
            page_contents: Optional list of page texts for extracting content
            
        Returns:
            List of all ContentChunks
        """
        all_chunks = []
        
        for section in sections:
            title = section.get("title", "Untitled")
            content = section.get("content") or section.get("text") or section.get("summary", "")
            page_start = section.get("start_index")
            page_end = section.get("end_index")
            
            if content:
                chunks = self.chunk_section(content, title, page_start, page_end)
                all_chunks.extend(chunks)
        
        return all_chunks


# Convenience function
def smart_chunk(
    content: str,
    title: str = "Document",
    page_start: int = 1,
    page_end: int = 1
) -> List[Dict]:
    """
    Quick chunking of a content string.
    
    Returns list of chunk dicts.
    """
    chunker = SmartChunker()
    chunks = chunker.chunk_section(content, title, page_start, page_end)
    return [c.to_dict() for c in chunks]


if __name__ == "__main__":
    # Demo
    print("Smart Chunker Demo")
    print("=" * 50)
    
    sample = """
# Installation Procedure

1. Turn off power at the main disconnect.
2. Verify all capacitors are discharged.
3. Connect the supply wiring per the diagram.
4. Install the control wiring.
5. Restore power.

## Operating Parameters

| Parameter | Min | Max | Unit |
|-----------|-----|-----|------|
| Supply Voltage | 380 | 480 | V |
| Operating Temp | 35 | 115 | °F |
| Flow Rate | 2.5 | 12 | GPM |

Refrigerant Charge: 15.5 lbs
Operating Pressure: 250 psi
Setpoint Range: 40-55°F

⚠️ WARNING: High voltage hazard. Qualified personnel only.

CAUTION: Do not exceed maximum pressure rating.
"""
    
    chunker = SmartChunker()
    chunks = chunker.chunk_section(sample, "Installation Guide", 1, 5)
    
    print(f"\nFound {len(chunks)} chunks:\n")
    for chunk in chunks:
        print(f"[{chunk.chunk_type.value}] {chunk.title}")
        print(f"  Tokens: ~{chunk.token_estimate}")
        print(f"  Preview: {chunk.content[:100]}...")
        print()
