# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Where each record came from: provenance for the explorer.

Reads the Reference nodes recorded when a workspace was populated (by the
onboarding agent, or by a workbook citing its Reference sheet), attaches them
to the instance table as a hidden column plus a readable ``Source`` summary,
and can open a source file from workspace storage. The storage handle is a
parameter here — the Streamlit shell supplies it from session state, the API
from the workspace context.
"""

from typing import Any, Dict, Optional, Tuple

import pandas as pd

from backend.graphdb import queries as gdb_queries

from backend.explorer.uris import extract_uri_fragment


def get_component_sources(client, component_type_label: str) -> Dict[str, Dict[str, Any]]:
    """Provenance per instance URI: where the record came from, and where any
    individual attribute came from when that differs.

    Shape: ``{instance_uri: {'instance': [ref, ...], 'attributes': {attr: [ref, ...]}}}``
    where each ref is ``{uri, label, type, url, date, comment}``. Empty when the
    graph carries no provenance, which is the normal case for a replica built
    before sources were recorded — the UI simply has nothing to show.
    """
    df = gdb_queries.get_component_sources(client, component_type_label)

    def cell(row, key: str) -> str:
        # An unbound OPTIONAL comes back as NaN, which is TRUTHY — `or` fallbacks
        # would silently keep it and render "nan" in the UI.
        val = row.get(key)
        return '' if val is None or pd.isna(val) else str(val)

    sources: Dict[str, Dict[str, Any]] = {}
    for _, row in df.iterrows():
        instance = cell(row, 'instance')
        if not instance:
            continue
        ref = {
            'uri': cell(row, 'source'),
            # A Reference with no label still has a readable id in its URI.
            'label': cell(row, 'sourceLabel') or extract_uri_fragment(cell(row, 'source')),
            'type': cell(row, 'sourceType'),
            'url': cell(row, 'sourceUrl'),
            'date': cell(row, 'sourceDate'),
            'comment': cell(row, 'sourceComment'),
        }
        entry = sources.setdefault(instance, {'instance': [], 'attributes': {}})
        if cell(row, 'scope') == 'attribute':
            attr = cell(row, 'attributeName') or '?'
            bucket = entry['attributes'].setdefault(attr, [])
        else:
            bucket = entry['instance']
        if not any(r['uri'] == ref['uri'] for r in bucket):
            bucket.append(ref)
    return sources


# Provenance rides on the frame the same way curve points do: a hidden column
# get_visible_columns strips, so the table and the CSV stay clean until asked for.
SOURCE_META_COLUMN = '_sources'
SOURCE_COLUMN = 'Source'


def attach_sources(df: pd.DataFrame, sources: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    """Attach per-instance provenance to the frame, keyed by the instance URI.

    Adds the hidden metadata column plus a readable ``Source`` summary. Both are
    absent when nothing in the graph has provenance, so a replica built before
    sources were recorded looks exactly as it did.
    """
    if df.empty or not sources or 'URI' not in df.columns:
        return df
    df = df.copy()
    df[SOURCE_META_COLUMN] = df['URI'].map(lambda u: sources.get(u))
    df[SOURCE_COLUMN] = df[SOURCE_META_COLUMN].map(summarize_sources)
    return df


def summarize_sources(entry: Optional[Dict[str, Any]]) -> str:
    """One cell's worth: the record's own source, plus any file that supplied some of
    the row's individual values (e.g. a catalogue file whose spec was copied down).
    Named, not counted — "+1" told the reader nothing; a count only when 3+ files
    would crowd the cell. Which attributes came from where is the per-instance panel's
    job. NB the `derivedFromCatalogue` link in the table is the model-level
    counterpart: it names the catalogue INSTANCE, this column the files."""
    if not entry:
        return ''
    names = [r['label'] for r in entry.get('instance', [])]
    extra = sorted({r['label'] for refs in entry.get('attributes', {}).values() for r in refs}
                   - set(names))
    text = ', '.join(names) if names else '—'
    if extra:
        text += (f" (+ {', '.join(extra)} for some values)" if len(extra) <= 2
                 else f" (+{len(extra)} files for some values)")
    return text


# How a Reference's recorded location is resolved to something viewable. Each entry
# is an opener taking (ref, storage) and they are tried in order, so a new kind of
# source is a new opener rather than a change to the viewer. `hasReferenceType` on
# the Reference says which kind it is; the openers below decide whether they can
# actually fetch it.
# Extensions we will not print into the page — a spreadsheet or an archive rendered
# as text is noise. They are offered for download instead.
_BINARY_SUFFIXES = ('.xlsx', '.xlsm', '.xls', '.zip', '.parquet', '.png', '.jpg', '.pdf')

# Where a bare relative path might live inside a workspace. The recorded location is
# relative to whatever produced it, so try the canonical data directories too.
_WORKSPACE_PREFIXES = ('', 'ingestion/input/', 'ingestion/output/', 'private_data_products/',
                       'timeseries/', 'docs/')


def resolve_workspace_file(ref: Dict[str, Any], storage) -> Optional[Tuple[str, str]]:
    """A path inside the given workspace storage -> (path, text), or None.

    ``storage`` is a WorkspaceStorage-like object (exists / isdir / read_text);
    the caller decides where it comes from — Streamlit passes the session's
    workspace context, the API the request's.
    """
    path = (ref.get('url') or '').strip()
    if not path or path.startswith(('http://', 'https://')):
        return None
    if storage is None:
        return None
    for prefix in _WORKSPACE_PREFIXES:
        candidate = f"{prefix}{path}"
        try:
            if not storage.exists(candidate) or storage.isdir(candidate):
                continue
            if candidate.lower().endswith(_BINARY_SUFFIXES):
                return candidate, ''          # found, but not printable
            return candidate, storage.read_text(candidate)
        except Exception:
            continue
    return None


SOURCE_OPENERS = (resolve_workspace_file,)


def open_source(ref: Dict[str, Any], storage) -> Optional[Tuple[str, str]]:
    """First opener that can fetch this source's content, else None."""
    for opener in SOURCE_OPENERS:
        try:
            found = opener(ref, storage)
        except Exception:
            found = None
        if found:
            return found
    return None
