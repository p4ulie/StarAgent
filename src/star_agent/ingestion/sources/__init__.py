"""Ingestion sources — one module per data source.

Each source yields :class:`~star_agent.ingestion.sources.base.Document` records.
Add a source by implementing :class:`Source` and registering it in
:data:`star_agent.ingestion.build_index.SOURCES`.
"""
