"""
RAG Tools for Agentic Retrieval
================================

Tools that allow the LLM to control the retrieval process:
- search_knowledge_base: Search for relevant documents
- refine_search: Refine a search with additional terms
- get_document_section: Get a specific section by page/identifier
- assess_confidence: Self-assess if enough info to answer

These tools enable multi-hop, iterative retrieval where the agent
decides when to search more vs when to answer.
"""

from typing import Optional, List, Dict, Any
import json
from agent_unified.tools.base import BaseTool, ToolResult
import re


class RetrievalContext:
    """Shared context to track what the agent has actually seen."""
    typing_llm: Optional[Any] = None

    def __init__(self, llm=None):
        self.retrieved_chunks: List[str] = []
        self.retrieved_tables: List[Dict] = []
        self.viewed_tables: set = set() # Set of table_ids (source:page:idx) the agent has explicitly fetched
        self.primary_query: str = "" # The original user query for policy enforcement
        self.typing_llm = llm
        
    async def is_underspecified(self) -> bool:
        """Determines if the current query is underspecified (lacks a model number)."""
        if not self.primary_query:
            return True
        from agent_advisory.equipment_patterns import has_specific_model_verified
        # Use tiered detection: Regex -> Context -> LLM Fallback
        has_model = await has_specific_model_verified(self.primary_query, llm=self.typing_llm)
        return not has_model
        
    def add_chunks(self, chunks: List[str]):
        """Register retrieved chunks for provenance checking."""
        self.retrieved_chunks.extend(chunks)

    def add_context(self, chunks: List[str], tables: List[Dict]):
        """Register chunks and structured tables."""
        self.retrieved_chunks.extend(chunks)
        # Add tables if they aren't already there
        existing_ids = {f"{t['source']}:{t['page']}:{tables.index(t)}" for t in self.retrieved_tables}
        for table in tables:
            # We need a stable ID. For now: source:page:index_on_page
            # Index is slightly tricky, let's just use source:page and allow multiple if needed
            # Or better, just store them all and search by ID.
            self.retrieved_tables.append(table)

    def mark_table_as_viewed(self, table_id: str):
        """Mark a table as FETCHED and thus available for verification."""
        self.viewed_tables.add(table_id)

    def is_table_viewed(self, table_id: str) -> bool:
        return table_id in self.viewed_tables

    def get_table_by_id(self, table_id: str) -> Optional[Dict]:
        """IDs are formatted as 'source:page:idx'"""
        for t in self.retrieved_tables:
            if t.get("id") == table_id:
                return t
        return None


class SearchKnowledgeBase(BaseTool):
    """Tool to search the technical knowledge base"""
    
    name: str = "search_knowledge_base"
    description: str = """Search the technical documentation knowledge base for relevant information.
Use this to find documentation about equipment specifications, procedures, parameters, and features.
Returns the top matching snippets with source, page numbers, and relevance scores."""
    
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query - be specific about what you're looking for"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results (integer 1-10). Use 3 for general queries, 5 for specific data lookups."
            }
        },
        "required": ["query"]
    }
    
    # Reference to dependencies (injected at runtime)
    _knowledge_base: Any = None
    _context: Optional[RetrievalContext] = None
    
    def set_dependencies(self, kb, context: Optional[RetrievalContext] = None):
        """Inject dependencies"""
        self._knowledge_base = kb
        self._context = context
    
    async def execute(
        self, 
        query: str, 
        top_k: int = 3
    ) -> ToolResult:
        if not self._knowledge_base:
            return self.fail_response("Knowledge base not initialized")
        
        try:
            # Force integer cast (Groq parser stability fix)
            try:
                top_k_int = int(top_k)
            except (ValueError, TypeError):
                top_k_int = 3
                
            # Perform the search
            if self._context:
                self._context.primary_query = query
                
            results = await self._knowledge_base.query_specs(
                query=query,
                limit=min(top_k_int, 10)
            )
            
            if not results:
                return self.success_response({
                    "found": 0,
                    "message": "No matching documents found. Try different search terms.",
                    "suggestions": [
                        "Try broader terms",
                        "Check equipment type spelling",
                        "Search for component names"
                    ]
                })
            
            # Register chunks for provenance
            if self._context:
                # Extract tables from metadata
                all_tables = []
                for r in results:
                    meta = r.get("metadata", {})
                    t_json = meta.get("table_data_json")
                    if t_json:
                        try:
                            tables = json.loads(t_json)
                            # Assign IDs to tables for subsequent fetching
                            for i, t in enumerate(tables):
                                t["id"] = f"{t['source']}:{t['page']}:{r.get('id', 'r')[:4]}_{i}"
                                all_tables.append(t)
                        except:
                            pass
                self._context.add_context([r.get("content", "") for r in results], all_tables)
            
            # Format results for the agent
            # query_specs returns: {content, metadata: {source, equipment_id, ...}, distance}
            formatted = []
            for r in results:
                meta = r.get("metadata", {})
                content = r.get("content", "")
                
                # Check for table data
                table_data = []
                t_json = meta.get("table_data_json")
                if t_json:
                    try:
                        table_data = json.loads(t_json)
                    except:
                        pass

                # Check for table data
                table_data = []
                t_json = meta.get("table_data_json")
                if t_json:
                    try:
                        table_data = json.loads(t_json)
                    except:
                        pass

                # Truncate tables for LLM stability in tool response
                # (Context already has the full data via add_context)
                # Only send metadata for tables.
                # Use the IDs assigned during context registration
                llm_table_data = []
                # We need to match the tables we just extracted with IDs
                # Since we just added them to the context, let's re-extract specifically for this result
                res_tables = []
                if t_json:
                    try:
                        res_tables = json.loads(t_json)
                        for i, t in enumerate(res_tables):
                            t_id = f"{t['source']}:{t['page']}:{r.get('id', 'r')[:4]}_{i}"
                            llm_table_data.append({
                                "id": t_id,
                                "header": t.get("headers", []),
                                "note": f"TABLE DETECTED. Call fetch_table_details(table_id='{t_id}') to view rows for verification."
                            })
                    except:
                        pass

                formatted.append({
                    "relevance": round(1 - r.get("distance", 0.5), 2),
                    "source": meta.get("source", "unknown"),
                    "page_start": meta.get("page_start", "unknown"),
                    "page_end": meta.get("page_end", "unknown"),
                    "snippet": content[:1000], # Reduced to 1000 for Groq stability
                    "has_table": meta.get("has_table", False) or "table" in content.lower(),
                    "table_metadata": llm_table_data
                })
            
            return self.success_response({
                "found": len(formatted),
                "results": formatted,
                "search_complete": True,
                "note": "If multiple tables are detected, call fetch_table_details for the most relevant one FIRST."
            })
            
        except Exception as e:
            return self.fail_response(f"Search error: {str(e)}")


class RefineSearch(BaseTool):
    """Tool to refine a search with additional context"""
    
    name: str = "refine_search"
    description: str = """Refine a previous search when initial results aren't sufficient.
Use this when:
- Initial search returned related but not exact information
- You need more specific details from a particular section
- You want to combine terms for a more targeted search"""
    
    parameters: dict = {
        "type": "object",
        "properties": {
            "original_query": {
                "type": "string",
                "description": "The original search query"
            },
            "refinement": {
                "type": "string",
                "description": "Additional terms or context to narrow the search"
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (default: 3, max: 10)"
            }
        },
        "required": ["original_query", "refinement"]
    }
    
    _knowledge_base: Any = None
    _context: Optional[RetrievalContext] = None
    
    def set_dependencies(self, kb, context: Optional[RetrievalContext] = None):
        self._knowledge_base = kb
        self._context = context

    def set_knowledge_base(self, kb):
        self._knowledge_base = kb
    
    async def execute(
        self,
        original_query: str,
        refinement: str,
        top_k: int = 3
    ) -> ToolResult:
        if not self._knowledge_base:
            return self.fail_response("Knowledge base not initialized")
        
        combined_query = f"{original_query} {refinement}"
        
        try:
            # Force integer cast
            try:
                top_k_int = int(top_k)
            except (ValueError, TypeError):
                top_k_int = 3

            results = await self._knowledge_base.query_specs(
                query=combined_query,
                limit=top_k_int
            )

            if results and self._context:
                # Extract tables from metadata
                all_tables = []
                for r in results:
                    meta = r.get("metadata", {})
                    t_json = meta.get("table_data_json")
                    if t_json:
                        try:
                            tables = json.loads(t_json)
                            for i, t in enumerate(tables):
                                t["id"] = f"{t.get('source', 'unknown')}:{t.get('page', 0)}:{r.get('id', 'r')[:4]}_{i}"
                                all_tables.append(t)
                        except Exception:
                            pass
                self._context.add_context([r.get("content", "") for r in results], all_tables)
            
            if not results:
                return self.success_response({
                    "found": 0,
                    "message": f"Refined search found no results. Consider searching for: {refinement} separately.",
                    "refined_query": combined_query
                })
            
            formatted = []
            for r in results:
                meta = r.get("metadata", {})
                content = r.get("content", "")
                
                # Check for table data
                table_data = []
                t_json = meta.get("table_data_json")
                if t_json:
                    try:
                        table_data = json.loads(t_json)
                    except:
                        pass

                # Truncate tables for LLM stability
                # Only send metadata for tables.
                llm_table_data = []
                if t_json:
                    try:
                        res_tables = json.loads(t_json)
                        for i, t in enumerate(res_tables):
                            t_id = f"{t.get('source', 'unknown')}:{t.get('page', 0)}:{r.get('id', 'r')[:4]}_{i}"
                            llm_table_data.append({
                                "id": t_id,
                                "header": t.get("headers", []),
                                "note": "TABLE DETECTED. Use fetch_table_details to see rows."
                            })
                    except:
                        pass

                formatted.append({
                    "relevance": round(1 - r.get("distance", 0.5), 2),
                    "source": meta.get("source", "unknown"),
                    "page_start": meta.get("page_start", "unknown"),
                    "page_end": meta.get("page_end", "unknown"),
                    "snippet": content[:1000], # Reduced for stability
                    "has_table": meta.get("has_table", False) or "table" in content.lower(),
                    "table_metadata": llm_table_data
                })
            
            return self.success_response({
                "found": len(formatted),
                "refined_query": combined_query,
                "results": formatted,
                "note": "FETCH tables individually if multiple IDs are provided."
            })
            
        except Exception as e:
            return self.fail_response(f"Refinement error: {str(e)}")


class FetchTableDetails(BaseTool):
    """Tool to fetch full rows of a table detected during search"""
    
    name: str = "fetch_table_details"
    description: str = """Fetch the full row content of a table. 
Use this when you see a 'table_metadata' entry in search results and need to verify numeric values.
You MUST call this to verify any numbers you cite from a table."""
    
    parameters: dict = {
        "type": "object",
        "properties": {
            "table_id": {
                "type": "string",
                "description": "The unique ID of the table (provided in search results)"
            }
        },
        "required": ["table_id"]
    }
    
    _context: Optional[RetrievalContext] = None
    
    def set_dependencies(self, context: Optional[RetrievalContext] = None):
        self._context = context
        
    async def execute(self, table_id: str) -> ToolResult:
        if not self._context:
            return self.fail_response("Context not initialized")
            
        table = self._context.get_table_by_id(table_id)
        if not table:
            return self.fail_response(f"Table {table_id} not found in current session context. Try searching for it first.")
            
        # Mark as viewed so AssessAnswerConfidence / ProvideAnswer know the LLM saw it
        self._context.mark_table_as_viewed(table_id)
        
        return self.success_response({
            "id": table_id,
            "headers": table.get("headers", []),
            "rows": table.get("rows", []),
            "source": table.get("source"),
            "page": table.get("page"),
            "verification_status": "READY. You have now explicitly viewed this data."
        })


class AssessAnswerConfidence(BaseTool):
    """Tool for the agent to self-assess if it has enough info"""
    
    name: str = "assess_answer_confidence"
    description: str = """Assess whether you have sufficient information to answer the question.
Use this BEFORE answering to determine if you need to search more.
Returns a recommendation: 'answer', 'search_more', or 'cannot_answer'."""
    
    parameters: dict = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The original question from the user"
            },
            "information_gathered": {
                "type": "string",
                "description": "Summary of what information you've found so far"
            },
            "confidence_level": {
                "type": "string",
                "description": "Your current confidence: high, medium, low, or none"
            }
        },
        "required": ["question", "information_gathered", "confidence_level"]
    }
    
    async def execute(
        self,
        question: str,
        information_gathered: str,
        confidence_level: str,
        missing_pieces: Optional[List[str]] = None
    ) -> ToolResult:
        missing = missing_pieces or []
        info_lower = information_gathered.lower()
        
        # ═══ REPRESENTATION DETECTION ═══
        has_table_data = any(kw in info_lower for kw in [
            "table", "performance data", "capacity", "flow rate",
            "rating", "cop", "kw", "pages", "page 6", "page 7", "page 9"
        ])
        has_procedural_data = any(kw in info_lower for kw in [
            "step", "procedure", "maintenance", "startup", "shutdown"
        ])
        has_spec_data = any(kw in info_lower for kw in [
            "compressor", "evaporator", "condenser", "feature", "component",
            "refrigerant", "design", "screw"
        ])
        
        # Classify the data representation
        if has_table_data:
            data_repr = "TABLE"
        elif has_procedural_data:
            data_repr = "PROCEDURAL"
        elif has_spec_data:
            data_repr = "SPECIFICATION"
        else:
            data_repr = "UNKNOWN"
        
        # ═══ TABLE DATA VERIFICATION ═══
        # Check if we ACTUALLY have table data in the context
        has_verified_table = False
        all_tables_viewed = True
        
        if self._context:
             has_tag = any("<table_data" in chunk for chunk in self._context.retrieved_chunks)
             has_struct = bool(self._context.retrieved_tables)
             
             # NEW: Check if the agent has actually CALLED fetch_table_details
             # for the tables it supposedly "found" in search results.
             if has_struct:
                 # If we have tables in context, but none are "viewed", then we can't verify numbers yet.
                 if not self._context.viewed_tables:
                     all_tables_viewed = False
             
             has_verified_table = (has_tag or has_struct) and all_tables_viewed
        
        # ═══ TABLE ENFORCEMENT ═══
        if has_table_data and not has_verified_table:
            # We suspect tables (keywords) but didn't find the tags
            # This is "Verified Absence" territory
            recommendation = "answer" # Allow them to say "cannot extract"
            guidance = (
                "TABLE KEYWORDS DETECTED BUT NO TABLE DATA FOUND. "
                "The documents reference tables (e.g. 'Page 6') but the actual table content is missing or not parseable. "
                "You MUST NOT guess numbers. "
                "You MUST states: 'The performance tables exist on [pages], but numeric values are not extractable in the current context.' "
                "Do NOT attempt to give a range."
            )
        elif has_table_data and not all_tables_viewed:
            recommendation = "search_more"
            guidance = (
                "TABLE METADATA DETECTED BUT NOT FETCHED. "
                "You have table IDs but you haven't viewed the rows yet. "
                "YOU MUST call 'fetch_table_details' for the relevant table IDs before you can answer with numbers. "
                "HINT: Fetch the most specific table FIRST. Do not fetch multi-tables in one turn if they are large."
            )
        elif has_verified_table:
            recommendation = "answer"
            if self._context and await self._context.is_underspecified():
                 guidance = (
                    "MODE B DETECTED: The user asked a broad question WITHOUT a specific model ID (e.g., '0312P'). "
                    "You MUST provide a deterministic summary of the table: "
                    "1. State the range (Min to Max) for the requested parameter. "
                    "2. List representative models (e.g., 'covering models 0312 to 1212'). "
                    "This aggregation is PERMITTED for underspecified queries. "
                    "If you see a 30XW-P/S/T/V, distinguish those if they have separate tables."
                 )
            else:
                 guidance = (
                    "MODE A DETECTED: The user asked a specific question with a model ID. "
                    "You MUST extract exact values from the table for that specific model. "
                    "If you fail to include the exact numbers, your answer will be REJECTED."
                 )
        elif has_spec_data:
            recommendation = "answer"
            guidance = (
                "SPECIFICATION DATA DETECTED. State what the documentation says directly. "
                "Name the component, its type, and its features. Point to the page."
            )
        elif confidence_level == "high":
            recommendation = "answer"
            guidance = "You have strong information. Proceed to answer confidently."
        elif confidence_level == "medium":
            recommendation = "answer"
            guidance = "Proceed to answer. Note any limitations but do NOT hedge."
        elif confidence_level == "low":
            if len(missing) > 2:
                recommendation = "search_more"
                guidance = f"Try one more search for: {', '.join(missing[:2])}"
            else:
                recommendation = "search_more" if self._context and await self._context.is_underspecified() else "answer"
                if recommendation == "search_more":
                    guidance = (
                        "LOW CONFIDENCE on a broad query. Try refining your search with keywords like "
                        "'performance data', 'nominal conditions', or 'flow rate table'. "
                        "The data is likely in a performance data section, not in general features."
                    )
                else:
                    guidance = (
                        "Low confidence does NOT mean refuse to answer. "
                        "State what you found, bound the uncertainty with numbers/ranges, point to pages. "
                        "Engineers don't say 'I don't know' — they say 'it depends on X, but ranges from Y to Z'."
                    )
        else:  # none
            recommendation = "search_more" if len(missing) > 0 else "answer"
            guidance = "Try different search terms, or answer with what you have."
        
        return self.success_response({
            "recommendation": recommendation,
            "guidance": guidance,
            "confidence": confidence_level,
            "data_representation": data_repr,
            "table_verified": has_verified_table,
            "missing_count": len(missing),
            "can_partially_answer": len(information_gathered) > 50
        })

    _context: Optional["RetrievalContext"] = None

    def set_dependencies(self, context: Optional["RetrievalContext"] = None):
        self._context = context


class ProvideAnswer(BaseTool):
    """Tool to provide the final answer to the user"""
    
    name: str = "provide_answer"
    description: str = """Provide the final answer to the technician's question.
Use this when you have gathered enough information to answer.
Structure your answer as a senior engineer would."""
    
    parameters: dict = {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "The complete answer to the question"
            },
            "sources": {
                "type": "string",
                "description": "Comma-separated list of sources/pages used in the answer"
            },
            "confidence": {
                "type": "string",
                "description": "Confidence level: high, medium, or low"
            },
            "next_action_hint": {
                "type": "string",
                "description": "Optional suggestion for what the technician could do next"
            }
        },
        "required": ["answer", "sources", "confidence"]
    }
    
    async def execute(
        self,
        answer: str,
        sources: str,
        confidence: str,
        next_action_hint: Optional[str] = None
    ) -> ToolResult:
        # ═══ BANNED PHRASE ENFORCEMENT ═══
        BANNED = [
            "does not contain enough information",
            "values are not explicitly stated",
            "exact values are not explicitly stated",
            "for more details, please refer to",
            "consult the official documentation",
            "consult the official product documentation",
            "I cannot determine",
            "the exact values are not provided",
            "it is recommended to consult",
            "it's recommended to refer to",
            "not explicitly stated in the provided",
            "not explicitly stated in the search",
            "for the most accurate and up-to-date",
        ]
        
        cleaned_answer = answer
        answer_lower = answer.lower()
        banned_found = []
        
        for phrase in BANNED:
            if phrase.lower() in answer_lower:
                banned_found.append(phrase)
        
        # If banned phrases detected, check if the answer ALSO contains real data
        if banned_found:
            # Before rejecting — check if the answer actually contains useful data numbers
            import re as _re
            _content_without_pages = _re.sub(r'pages?\s+\d+(?:-\d+)?(?:,\s*\d+)*', '', answer, flags=_re.IGNORECASE)
            _has_data = bool(_re.search(r'\d+(?:\.\d+)?\s*(?:kW|kPa|L/s|°C|%|COP|EER|A|V|Hz|dB|kg|mm|m³)', _content_without_pages))
            
            if _has_data:
                # The answer has real data — strip the hedging sentences rather than rejecting
                cleaned_answer = answer
                for phrase in banned_found:
                    # Remove the sentence containing the banned phrase
                    pattern = r'[^.]*' + _re.escape(phrase) + r'[^.]*\.\s*'
                    cleaned_answer = _re.sub(pattern, '', cleaned_answer, flags=_re.IGNORECASE)
                answer = cleaned_answer.strip()
            else:
                return self.fail_response(
                    f"ANSWER REJECTED — contains banned phrases: {banned_found}. "
                    f"Rewrite your answer. Remember: "
                    f"If data is in tables, say 'values vary by model — see page X'. "
                    f"If you found performance sections, summarize what varies. "
                    f"Engineers bound the problem, they don't disclaim it. "
                    f"Call provide_answer again with a corrected answer."
                )
            
        # ═══ EMPTY POINTER ENFORCEMENT ═══
        # If the answer says "values vary" or "depends on", it MUST contain extracted numbers (not just page numbers).
        import re
        
        has_hedging = any(phrase in answer_lower for phrase in ["vary", "varies", "depend", "refer to", "see page"])
        
        # Allow explicit "Degraded Mode" admission
        is_degraded = any(phrase in answer_lower for phrase in ["cannot extract", "unable to read", "too complex to summarize"])
        
        if has_hedging and not is_degraded:
            # Strip page references to see if actual data numbers exist
            # Matches "Page 12", "Pages 6-9", "page 4"
            content_without_pages = re.sub(r'pages?\s+\d+(?:-\d+)?(?:,\s*\d+)*', '', answer, flags=re.IGNORECASE)
            
            # Check for remaining digits (data)
            has_data_numbers = bool(re.search(r'\d', content_without_pages))
            
            if not has_data_numbers:
                 return self.fail_response(
                    "ANSWER REJECTED. You pointed to pages but extracted NO data numbers. "
                )

        # ═══ BRUTAL RULE: NO TABLE = NO NUMBERS ═══
        if self._context and not is_degraded:
            has_tag = any("<table_data" in chunk for chunk in self._context.retrieved_chunks)
            has_viewed_struct = any(self._context.is_table_viewed(t.get("id", "")) for t in self._context.retrieved_tables)
            has_verified_table = has_tag or has_viewed_struct
            
            # Extract candidates
            candidates = re.findall(r'\b\d+(?:\.\d+)?\b', answer)
            
            # Filter candidates (remove pages, years)
            data_numbers = []
            for num in candidates:
                if re.search(r'pages?\s+' + re.escape(num), answer, re.IGNORECASE): continue
                if re.search(r'20\d\d', num): continue
                if re.search(r'table\s+' + re.escape(num), answer, re.IGNORECASE): continue # "Table 1"
                data_numbers.append(num)

            if data_numbers and not has_verified_table:
                 return self.fail_response(
                    "STRICT PROVENANCE CHECK FAILED. You cited data numbers but NO table was found in the context. "
                    "We enforce a strict rule: If the system cannot parse the table info (no <table_data> tags), you MUST NOT output numbers. "
                    "This is to prevent soft hallucinations. "
                    "Please rewrite your answer to state: 'The performance tables exist on [pages], but numeric values are not extractable in the current context.'"
                )

        # ═══ PROVENANCE MATCHING (Text + Structured Tables) ═══
        if self._context and not is_degraded:
            hallucinations = []
            full_context_text = " ".join(self._context.retrieved_chunks)
            
            # Extract ALL numbers from structured tables for fallback matching
            # BUT ONLY from tables the agent has actually "viewed" via fetch_table_details
            table_numbers = set()
            viewed_count = 0
            for table in self._context.retrieved_tables:
                 if self._context.is_table_viewed(table.get("id", "")):
                      viewed_count += 1
                      for row in table.get("rows", []):
                           for cell in row:
                                # Verbatim cell matching: extract numbers from cell
                                found = re.findall(r'\b\d+(?:\.\d+)?\b', str(cell))
                                table_numbers.update(found)

            # Rule: If numbers are found in tables but tables aren't viewed, it's a soft hallucination (guessing)
            for num in data_numbers:
                if num in full_context_text:
                    continue
                if num in table_numbers:
                    continue
                hallucinations.append(num)
            
            if hallucinations:
                # Check if the hallucinations exist in any UNVIEWED table
                unviewed_match = False
                for table in self._context.retrieved_tables:
                    if not self._context.is_table_viewed(table.get("id", "")):
                        for row in table.get("rows", []):
                            for cell in row:
                                if num in str(cell): unviewed_match = True
                
                if unviewed_match:
                     return self.fail_response(
                        f"PROVENANCE CHECK FAILED. You cited numbers that appear to be in a table, but YOU DID NOT FETCH the table details. "
                        f"You are not allowed to guess ranges or values from metadata headers. "
                        f"Call 'fetch_table_details' for the relevant table ID, verify the exact cell, and then provide the answer."
                    )
                
                return self.fail_response(
                    f"PROVENANCE CHECK FAILED. You cited numbers {hallucinations} which were NOT found in the retrieved documents or fetched tables. "
                    f"You are strictly forbidden from hallucinating numbers or performing unchecked calculations. "
                    f"Only quote numbers that literally exist in the source content. "
                )
            
            # ═══ AGGREGATION POLICY ═══
            # If the answer provides a NUMERIC RANGE (n to m), ensure the query asked for it OR it's underspecified.
            is_range = bool(re.search(r'\d+(?:\.\d+)?\s*(?:to|and|-|—)\s*\d+(?:\.\d+)?', answer))
            
            # Check the ORIGINAL QUERY stored in context
            query_asks_range = False
            is_underspecified = False
            if self._context:
                is_underspecified = await self._context.is_underspecified()
                if self._context.primary_query:
                    q_lower = self._context.primary_query.lower()
                    query_asks_range = any(kw in q_lower for kw in ["range", "min", "max", "variation", "spread", "distribution"])
            
            # Policy: Block synthesized ranges if query was specific (Mode A) and didn't ask for range
            if is_range and not query_asks_range and not is_underspecified and confidence in ["high", "medium"]:
                # Stricter: block range aggregation if specific model data is likely in a viewed table
                return self.fail_response(
                    "POLICY VIOLATION: You provided a synthesized range for a specific query. "
                    "In engineering manuals, if a model number is specified, you must provide the EXACT value for that model. "
                    "Check the table rows for the specific model number."
                )
        
        # Format the final response
        source_list = [s.strip() for s in sources.split(",")] if sources else []
        response = {
            "answer": cleaned_answer,
            "sources": source_list,
            "confidence": confidence,
            "is_final": True
        }
        
        if next_action_hint:
            response["next_action"] = next_action_hint
        
        return self.success_response(response, system="Answer provided. Terminate.")

    _context: Optional[RetrievalContext] = None

    def set_dependencies(self, context: Optional[RetrievalContext] = None):
        self._context = context



def create_rag_tools(knowledge_base=None, llm=None) -> List[BaseTool]:
    """Factory function to create RAG tools with injected dependencies"""
    # Create shared context for provenance tracking
    context = RetrievalContext(llm=llm)
    
    search = SearchKnowledgeBase()
    search.set_dependencies(knowledge_base, context)
    
    refine = RefineSearch()
    refine.set_dependencies(knowledge_base, context)
    
    fetch = FetchTableDetails()
    fetch.set_dependencies(context)
    
    assess = AssessAnswerConfidence()
    assess.set_dependencies(context)
    
    answer = ProvideAnswer()
    answer.set_dependencies(context)
    
    return [search, refine, fetch, assess, answer]
