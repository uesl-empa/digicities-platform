# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Readable names out of URIs.

Instance and property URIs arrive in any namespace pattern a workspace author
chose (fragment style, path style, or both), so these helpers never assume a
particular prefix — they peel off the last meaningful part.
"""

import re


def extract_uri_fragment(uri: str) -> str:
    """Extract the last part of a URI - FIXED for any namespace pattern"""
    if not uri:
        return ''

    # Handle URIs with fragment identifiers (#)
    if '#' in uri:
        fragment = uri.split('#')[-1]
        return fragment if fragment else uri.split('/')[-1]

    # Handle URIs with path segments (/)
    elif '/' in uri:
        path_part = uri.split('/')[-1]
        return path_part if path_part else uri

    # Return as-is if no separators found
    else:
        return uri


def extract_property_name(property_uri: str) -> str:
    """Extract property name from URI - ENHANCED"""
    if not property_uri:
        return ''

    # Common namespace patterns
    namespaces = [
        'https://digicities.info/ontology#',
        'http://qudt.org/schema/qudt/',
        'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
        'http://www.w3.org/2000/01/rdf-schema#',
        'http://purl.org/dc/terms/'
    ]

    # Try exact namespace matches first
    for ns in namespaces:
        if property_uri.startswith(ns):
            return property_uri[len(ns):]

    # Fallback to generic fragment extraction
    return extract_uri_fragment(property_uri)


def extract_readable_instance_name(uri: str) -> str:
    """Extract a readable name from instance URIs - handles any namespace pattern"""
    if not uri:
        return ''

    # Extract the local part after # or /
    local_part = extract_uri_fragment(uri)

    # If it's just a simple identifier, return it
    if local_part and len(local_part) <= 20 and not '/' in local_part:
        return local_part

    # For longer URIs, try to extract meaningful parts
    # Split on common separators and take the last meaningful part
    parts = re.split(r'[/#]', uri)
    meaningful_parts = [part for part in parts if part and len(part) > 0]

    if meaningful_parts:
        return meaningful_parts[-1]

    return uri
