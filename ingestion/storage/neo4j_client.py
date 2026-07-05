from contextlib import contextmanager
from typing import Any, Generator, Optional

from neo4j import Driver, GraphDatabase, Session

from ingestion.config import Settings, get_settings
from ingestion.exceptions import GraphStoreError


class Neo4jClient:
    """
    Typed wrapper for Neo4j medical knowledge graph operations.

    Node labels used:   Disease, Drug, Symptom, Procedure, Treatment,
                        ResearchPaper, Guideline, Document
    Relationship types: TREATS, CAUSES, CONTRAINDICATES, MENTIONS,
                        RELATED_TO, MENTIONED_IN, PART_OF
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        cfg = settings or get_settings()
        self._driver: Driver = GraphDatabase.driver(
            cfg.neo4j_uri,
            auth=(cfg.neo4j_user, cfg.neo4j_password),
        )

    # ── Session management ────────────────────────────────────────────────────

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        session = self._driver.session()
        try:
            yield session
        finally:
            session.close()

    # ── Generic query ─────────────────────────────────────────────────────────

    def execute_query(
        self, cypher: str, params: Optional[dict[str, Any]] = None
    ) -> list[dict[str, Any]]:
        """Run any Cypher query and return results as a list of dicts."""
        try:
            with self._session() as session:
                result = session.run(cypher, params or {})
                return [dict(record) for record in result]
        except Exception as exc:
            raise GraphStoreError(
                f"Query failed: {exc}\nCypher: {cypher[:200]}"
            ) from exc

    # ── Node operations ───────────────────────────────────────────────────────

    def upsert_entity(
        self,
        label: str,
        properties: dict[str, Any],
        match_keys: list[str],
    ) -> None:
        """
        MERGE a node by match_keys; SET all other properties on create and match.
        Example: upsert_entity("Drug", {"name": "Metformin", "rxnorm_code": "6809"}, ["rxnorm_code"])
        """
        match_props  = {k: v for k, v in properties.items() if k in match_keys}
        update_props = {k: v for k, v in properties.items() if k not in match_keys}

        merge_clause = ", ".join(f"{k}: ${k}" for k in match_props)
        set_clause   = ", ".join(f"n.{k} = ${k}" for k in update_props)

        cypher = f"MERGE (n:{label} {{{merge_clause}}})"
        if set_clause:
            cypher += f" ON CREATE SET {set_clause} ON MATCH SET {set_clause}"

        self.execute_query(cypher, properties)

    def get_entity(
        self, label: str, match_key: str, match_value: Any
    ) -> Optional[dict[str, Any]]:
        """Return the first node matching the given label + property, or None."""
        result = self.execute_query(
            f"MATCH (n:{label}) WHERE n.{match_key} = $value RETURN n LIMIT 1",
            {"value": match_value},
        )
        return dict(result[0]["n"]) if result else None

    # ── Relationship operations ───────────────────────────────────────────────

    def upsert_relationship(
        self,
        from_label:  str,
        from_match:  dict[str, Any],
        rel_type:    str,
        to_label:    str,
        to_match:    dict[str, Any],
        rel_props:   Optional[dict[str, Any]] = None,
    ) -> None:
        """
        MERGE a relationship between two matched nodes.
        Example:
            upsert_relationship(
                "Drug", {"rxnorm_code": "6809"},
                "TREATS",
                "Disease", {"icd10_code": "E11"},
            )
        """
        from_params = {f"from_{k}": v for k, v in from_match.items()}
        to_params   = {f"to_{k}":   v for k, v in to_match.items()}

        from_where  = " AND ".join(f"a.{k} = $from_{k}" for k in from_match)
        to_where    = " AND ".join(f"b.{k} = $to_{k}"   for k in to_match)

        rel_set_clause = "SET r += $rel_props" if rel_props else ""

        cypher = (
            f"MATCH (a:{from_label}) WHERE {from_where} "
            f"MATCH (b:{to_label})   WHERE {to_where} "
            f"MERGE (a)-[r:{rel_type}]->(b) {rel_set_clause}"
        )

        params: dict[str, Any] = {**from_params, **to_params}
        if rel_props:
            params["rel_props"] = rel_props

        self.execute_query(cypher, params)

    def link_chunk_to_entities(
        self, chunk_id: str, entity_ids: list[str], document_id: str
    ) -> None:
        """
        Create MENTIONED_IN relationships from entity nodes to the document node.
        Used by the GraphAwareChunker to support GraphRAG retrieval.
        """
        if not entity_ids:
            return
        cypher = (
            "MATCH  (d:Document {document_id: $doc_id}) "
            "UNWIND $ids AS eid "
            "MATCH  (e) WHERE e.entity_id = eid "
            "MERGE  (e)-[:MENTIONED_IN {chunk_id: $chunk_id}]->(d)"
        )
        self.execute_query(cypher, {
            "doc_id":   document_id,
            "ids":      entity_ids,
            "chunk_id": chunk_id,
        })

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def verify_connectivity(self) -> bool:
        """Return True if the database is reachable."""
        try:
            self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
