# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

import pandas as pd


def process_excel_to_ttl(project_uri, file_path, output_ttl_path, uri_mode="default",
                         default_units=None):
    """
    Extended script to handle different attribute types.
    Now with fixed curve data processing and correct annotation format.
    Updated to include datasource functionality and time-based sources (Historic/Live/Future).
    Enhanced to handle multiple time-based variants of the same attribute.
    Modified to handle Live attributes with /ts pattern and reorder output.
    UPDATED: Changed time series structure to use forward links from attributes.
    UPDATED: Added direct time series reference properties to attributes.
    UPDATED: Added attribute type declarations and merged with additional functionality.
    UPDATED: Added support for Class Object and Identifier attribute types.
    UPDATED: Added support for Event attribute type with temporal precision handling.
    FIXED: Event type formatting and float year recognition.
    UPDATED: Added support for Resource attribute type.
    NEW: Added support for SimpleValue and CustomPhysicalRatio attribute types.
    FIXED: Class Object handling to create direct predicate relationships.
    NEW: Added URI mode parameter to handle different URI generation patterns.
    NEW: Added LinkedClassObjectType support for ClassObject attributes.
    UPDATED: Added dici_onto:hasUnitLabel (DatatypeProperty) alongside qudt:unit (ObjectProperty)
             for Physical, UnitBasedCost, Geospatial, Curve (xUnitLabel/yUnitLabel), and
             TimeSeries (Historic/Live/Future) attribute types to provide a human-readable
             string unit representation for applications, maintaining full backwards compatibility.
             CustomPhysicalRatio now uses dici_onto:hasUnitLabel exclusively (ratio units have
             no single QUDT IRI).

    Unit label strategy per attribute type:
      Physical        -> qudt:unit <IRI> (kept) + dici_onto:hasUnitLabel "string" (new)
      UnitBasedCost   -> qudt:unit <IRI> (kept) + dici_onto:hasUnitLabel "string" (new)
      Geospatial      -> qudt:unit <IRI> (kept) + dici_onto:hasUnitLabel "string" (new)
      Curve           -> dici_onto:xUnit unit:<IRI> (kept) + dici_onto:xUnitLabel "string" (new)
                         dici_onto:yUnit unit:<IRI> (kept) + dici_onto:yUnitLabel "string" (new)
      Historic/Future -> qudt:unit <IRI> on TimeSeries (kept) + dici_onto:hasUnitLabel "string" (new)
      Live            -> qudt:unit <IRI> on TimeSeries (kept) + dici_onto:hasUnitLabel "string" (new)
      CustomPhysical  -> dici_onto:hasUnitLabel "num/den" ONLY (qudt:unit string was invalid before)
      SimpleCost      -> no unit (unchanged)
      SimpleValue     -> no unit (unchanged)
      Event           -> no unit (unchanged)
      Categorical     -> no unit (unchanged)
      Identifier      -> no unit (unchanged)
      Annotation      -> no unit (unchanged)
      ClassObject     -> no unit (unchanged)

    Args:
        project_uri (str): The base project URI
        file_path (str): Path to the Excel file
        output_ttl_path (str): Path for the output TTL file
        uri_mode (str): URI generation mode - "default", "full-uri-in-cell", or "complete-project-uri"
    """
    import pandas as pd
    import math
    import rdflib
    import re
    import warnings
    import datetime
    from collections import defaultdict

    # Suppress openpyxl data validation warnings
    warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

    def is_nonempty(val):
        if pd.isna(val):
            return False
        if isinstance(val, str):
            s = val.strip().lower()
            if s == "" or s == "na":
                return False
        return True

    def format_decimal(num):
        if num.is_integer():
            return f"{int(num)}.0"
        else:
            return f"{num}"

    def generate_instance_uri(project_uri, sheet_name, row_id, uri_mode):
        """Generate instance URI based on the specified URI mode"""
        if uri_mode == "default":
            return f"<{project_uri}/{sheet_name}/{row_id}>"
        elif uri_mode == "full-uri-in-cell":
            # Assume row_id contains the complete URI
            return f"<{row_id}>"
        elif uri_mode == "complete-project-uri":
            # project_uri should end with # and row_id is just the identifier
            return f"<{project_uri}{row_id}>"
        else:
            raise ValueError(f"Unknown uri_mode: {uri_mode}")

    def generate_attribute_uri(instance_uri_content, attr_name, uri_mode):
        """Generate attribute URI based on the instance URI and mode"""
        # Remove the angle brackets from instance_uri_content for processing
        base_uri = instance_uri_content.strip('<>')

        if uri_mode == "default":
            return f"<{base_uri}/{attr_name}>"
        elif uri_mode == "full-uri-in-cell":
            return f"<{base_uri}/{attr_name}>"
        elif uri_mode == "complete-project-uri":
            return f"<{base_uri}/{attr_name}>"
        else:
            raise ValueError(f"Unknown uri_mode: {uri_mode}")

    def generate_timeseries_uri(instance_uri_content, attr_name, time_type, uri_mode):
        """Generate time series URI based on the instance URI and mode"""
        # Remove the angle brackets from instance_uri_content for processing
        base_uri = instance_uri_content.strip('<>')

        if uri_mode == "default":
            return f"<{base_uri}/{attr_name}_{time_type.lower()}/ts>"
        elif uri_mode == "full-uri-in-cell":
            return f"<{base_uri}/{attr_name}_{time_type.lower()}/ts>"
        elif uri_mode == "complete-project-uri":
            return f"<{base_uri}/{attr_name}_{time_type.lower()}/ts>"
        else:
            raise ValueError(f"Unknown uri_mode: {uri_mode}")

    def add_specific_attr_uri(sheet, attr_name, attr_uri, specific_attr_list):
        s_attr_uri = f"dici_onto:has{sheet}{attr_name}Attribute {attr_uri}"
        if s_attr_uri not in specific_attr_list:
            specific_attr_list.append(s_attr_uri)

    def get_clean_header_value(col_tuple, index, is_nonempty_func):
        """Extract header value, filtering out pandas Unnamed placeholders"""
        if len(col_tuple) <= index:
            return None
        val = col_tuple[index]
        if not is_nonempty_func(val):
            return None
        val_str = str(val).strip()
        if val_str.startswith("Unnamed:") or val_str.startswith("Unnamed_"):
            return None
        return val_str

    def process_curve_data(value):
        """Process curve data from string format '[(x,y);(x,y);...]'"""
        try:
            # Remove any outer quotes if present
            value = value.strip('"\'')

            # Split the string into point pairs and process each pair
            points_str = value.strip('[]').split(';')
            formatted_points = []

            for point_str in points_str:
                # Extract x and y values using regex
                match = re.match(r'\((\d+\.?\d*),(\d+\.?\d*)\)', point_str.strip())
                if match:
                    x_str = format_decimal(float(match.group(1)))
                    y_str = format_decimal(float(match.group(2)))
                    formatted_points.append(f'    [{x_str:>8}, {y_str:>10}]')

            return formatted_points
        except Exception as e:
            print(f"Error processing curve data: {e}")
            return []

    def get_datasource_lines(datasource_value, ref_uri_map):
        """Split a datasource value on ';' and resolve each part.

        Parts that match a known reference ID → prov:wasDerivedFrom <ref_uri>.
        Parts that don't match → dcterms:source "..."^^xsd:string (backwards compat).
        Returns a list of bare predicate-object strings (no leading tab, no trailing ; or .).
        """
        parts = [v.strip() for v in str(datasource_value).split(';') if v.strip()]
        lines = []
        for part in parts:
            if part in ref_uri_map:
                lines.append(f'prov:wasDerivedFrom {ref_uri_map[part]}')
            else:
                lines.append(f'dcterms:source "{part}"^^xsd:string')
        return lines

    # Validate uri_mode parameter
    valid_modes = ["default", "full-uri-in-cell", "complete-project-uri"]
    if uri_mode not in valid_modes:
        raise ValueError(f"Invalid uri_mode '{uri_mode}'. Must be one of: {valid_modes}")

    # Check if the Excel file has a 7th header row with "LinkedClassObjectType"
    # First, read just the header area to detect the structure
    def has_linked_class_object_type_header(file_path):
        """Check if any sheet has LinkedClassObjectType in row index 6 (7th row)"""
        try:
            # Read raw Excel without treating rows as headers
            raw_sheets = pd.read_excel(file_path, sheet_name=None, header=None, nrows=7)
            for sheet_name, raw_df in raw_sheets.items():
                if sheet_name in ("Data Validation", "Reference"):
                    continue
                if len(raw_df) >= 7:
                    # Check row index 6 (7th row, 0-indexed) for "LinkedClassObjectType"
                    row_6_values = raw_df.iloc[6].astype(str).str.strip().tolist()
                    if "LinkedClassObjectType" in row_6_values:
                        return True
            return False
        except Exception as e:
            print(f"Warning: Could not detect header structure: {e}")
            return False

    # Determine number of header rows based on file structure
    has_7th_header = has_linked_class_object_type_header(file_path)

    if has_7th_header:
        # Read Excel file with 7 header rows to include LinkedClassObjectType
        sheets = pd.read_excel(file_path, sheet_name=None, header=[0, 1, 2, 3, 4, 5, 6])
    else:
        # Read Excel file with 6 header rows (original behavior)
        sheets = pd.read_excel(file_path, sheet_name=None, header=[0, 1, 2, 3, 4, 5])

    ttl_lines = []
    # TTL prefixes
    ttl_lines.extend([
        "@prefix dici_onto: <https://digicities.info/ontology#> .",
        "@prefix qudt: <http://qudt.org/schema/qudt/> .",
        "@prefix unit: <http://qudt.org/vocab/unit/> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix cur: <http://qudt.org/vocab/currency/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        # Empty prefix maps to the project's own namespace so things like
        # :BaseCarrier (free-form annotation columns) get well-formed,
        # project-scoped IRIs instead of the bogus placeholder.
        f"@prefix : <{project_uri}#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix schema: <https://schema.org/> .",
        "",
        "",
    ])

    # Store instance declarations and attribute value declarations separately
    instance_declarations = []
    attribute_value_declarations = []
    class_object_declarations = []  # New: store class object declarations separately
    identifier_declarations = []  # New: store identifier declarations separately
    reference_declarations = []  # Reference class definition and instances
    ref_uri_map = {}  # maps reference ID string -> URI string e.g. "<project_uri/Reference/ref_id>"

    # --- Process Reference tab (before main loop so ref_uri_map is populated) ---
    if "Reference" in sheets:
        ref_df = sheets["Reference"]

        reference_declarations.extend([
            "# --- Reference class and instances ---",
            "dici_onto:Reference a owl:Class ;",
            "\trdfs:subClassOf prov:Entity ;",
            '\trdfs:label "Reference" ;',
            '\trdfs:comment "A citable information source used in a Digicities scenario or dataset." .',
            "",
        ])

        ref_id_col = None
        for col in ref_df.columns:
            if col[0] == "id":
                ref_id_col = col
                break

        if ref_id_col is not None:
            for _, ref_row in ref_df.iterrows():
                ref_id = ref_row[ref_id_col]
                if not is_nonempty(ref_id):
                    continue
                ref_id_str = str(ref_id).strip()
                ref_uri = f"<{project_uri}/Reference/{ref_id_str}>"
                ref_uri_map[ref_id_str] = ref_uri

                ref_props = [f"{ref_uri} a dici_onto:Reference"]

                for col in ref_df.columns:
                    attr_name_r = str(col[0]).strip()
                    if attr_name_r == "id":
                        continue
                    if attr_name_r.startswith("Unnamed:") or attr_name_r.startswith("Unnamed_"):
                        continue
                    val = ref_row[col]
                    if not is_nonempty(val):
                        continue
                    val_str = str(val).strip()

                    if attr_name_r == "description":
                        ref_props.append(f'\trdfs:label "{val_str}"')
                    elif attr_name_r == "ReferenceType":
                        ref_props.append(f'\tdici_onto:hasReferenceType dici_onto:{val_str}')
                    elif attr_name_r == "URL":
                        ref_props.append(f'\tschema:url "{val_str}"^^xsd:anyURI')
                    elif attr_name_r == "comment":
                        ref_props.append(f'\trdfs:comment "{val_str}"')
                    elif attr_name_r == "AccessDate":
                        if isinstance(val, (datetime.datetime, datetime.date)):
                            date_str = val.strftime('%Y-%m-%d') if hasattr(val, 'strftime') else str(val)
                        else:
                            parsed = None
                            for fmt in ['%Y-%m-%d', '%d.%m.%Y', '%d/%m/%Y']:
                                try:
                                    parsed = datetime.datetime.strptime(val_str, fmt).strftime('%Y-%m-%d')
                                    break
                                except ValueError:
                                    continue
                            date_str = parsed if parsed else val_str
                        ref_props.append(f'\tdcterms:dateAccessed "{date_str}"^^xsd:date')

                reference_declarations.append(" ;\n".join(ref_props) + " .")
                reference_declarations.append("")

    # Track which attributes we've already logged a default-unit stamp for, so a
    # workbook with many rows doesn't repeat the message per instance.
    stamped_default_logged = set()

    for sheet_name, df in sheets.items():
        if sheet_name in ("Data Validation", "Reference"):
            continue

        # Find the "id" column
        id_col = None
        for col in df.columns:
            if col[0] == "id":
                id_col = col
                break
        if id_col is None:
            continue

        # Group columns by attribute name to identify time-based variants
        attr_groups = defaultdict(list)
        for col in df.columns:
            col_name = col[0]
            if col_name == "id":
                continue
            if col_name.endswith("_datasource"):
                continue
            attr_groups[col_name].append(col)

        # Process each row
        for _, row in df.iterrows():
            row_id = row[id_col]
            if not is_nonempty(row_id):
                continue

            # Generate instance URI using the specified mode
            instance_uri = generate_instance_uri(project_uri, sheet_name, row_id, uri_mode)
            instance_lines = [f"{instance_uri} a dici_onto:{sheet_name}"]

            instance_attr_uris = set()
            attr_uri_list = []
            specific_attr_uri_list = []
            annotation_lines = []
            class_object_lines = []  # New: collect class object properties for this instance
            identifier_uris = []  # New: collect identifier URIs for this instance

            # Process each attribute group
            for attr_name, cols in attr_groups.items():
                # Check if this attribute has time-based variants
                time_variants = {}
                non_time_cols = []

                for col in cols:
                    attr_type = col[1] if len(col) > 1 else None
                    if attr_type in ["Historic", "Live", "Future"]:
                        time_variants[attr_type] = col
                    else:
                        non_time_cols.append(col)

                # Process time-based variants
                if time_variants:
                    # Create a single attribute URI for all time variants
                    single_attr_uri = generate_attribute_uri(instance_uri, attr_name, uri_mode)

                    if single_attr_uri not in instance_attr_uris:
                        instance_attr_uris.add(single_attr_uri)
                        attr_uri_list.append(single_attr_uri)

                    add_specific_attr_uri(sheet_name, attr_name, single_attr_uri, specific_attr_uri_list)

                    # Get common properties from the first time variant
                    first_col = next(iter(time_variants.values()))
                    qudt_unit = get_clean_header_value(first_col, 2, is_nonempty)
                    # Stamp the ontology default unit when the workbook gives none, so
                    # the instance stays self-describing. Never silent — it logs (once).
                    if not qudt_unit and default_units and attr_name in default_units:
                        qudt_unit = default_units[attr_name]
                        if attr_name not in stamped_default_logged:
                            print(f"[replica-builder] '{attr_name}': no unit in workbook — "
                                  f"stamped ontology default unit:{qudt_unit}")
                            stamped_default_logged.add(attr_name)

                    # Build the single attribute declaration with all time series references
                    attr_properties = [
                        f"a dici_onto:{attr_name}",
                        f"a dici_onto:DynamicAttribute"
                    ]

                    # Collect time series declarations
                    ts_declarations = []

                    for time_type, col in time_variants.items():
                        value = row[col]
                        if not is_nonempty(value):
                            continue

                        # Create TimeSeries URI
                        ts_attr_uri = generate_timeseries_uri(instance_uri, attr_name, time_type, uri_mode)

                        if time_type == "Historic":
                            attr_properties.extend([
                                f"dici_onto:hasHistoricTimeSeries {ts_attr_uri}",
                                f'dici_onto:hasHistoricTimeSeriesReference "{value}"^^xsd:string'
                            ])

                            # Build TimeSeries node lines
                            # qudt:unit <IRI> preserved for backwards compat; hasUnitLabel added for string access
                            if qudt_unit:
                                ts_lines = [
                                    f"{ts_attr_uri} a dici_onto:TimeSeries ;",
                                    f'\tdici_onto:storedAt "{value}"^^xsd:string ;',
                                    f'\tdici_onto:hasFileName "{value}"^^xsd:string ;',
                                    f'\tqudt:unit <http://qudt.org/vocab/unit/{qudt_unit}> ;',
                                    f'\tdici_onto:hasUnitLabel "{qudt_unit}"^^xsd:string .'
                                ]
                            else:
                                ts_lines = [
                                    f"{ts_attr_uri} a dici_onto:TimeSeries ;",
                                    f'\tdici_onto:storedAt "{value}"^^xsd:string ;',
                                    f'\tdici_onto:hasFileName "{value}"^^xsd:string .'
                                ]

                            ts_declarations.extend(ts_lines)
                            ts_declarations.append("")

                        elif time_type == "Future":
                            attr_properties.extend([
                                f"dici_onto:hasFutureTimeSeries {ts_attr_uri}",
                                f'dici_onto:hasFutureTimeSeriesReference "{value}"^^xsd:string'
                            ])

                            if qudt_unit:
                                ts_lines = [
                                    f"{ts_attr_uri} a dici_onto:TimeSeries ;",
                                    f'\tdici_onto:storedAt "{value}"^^xsd:string ;',
                                    f'\tdici_onto:hasFileName "{value}"^^xsd:string ;',
                                    f'\tqudt:unit <http://qudt.org/vocab/unit/{qudt_unit}> ;',
                                    f'\tdici_onto:hasUnitLabel "{qudt_unit}"^^xsd:string .'
                                ]
                            else:
                                ts_lines = [
                                    f"{ts_attr_uri} a dici_onto:TimeSeries ;",
                                    f'\tdici_onto:storedAt "{value}"^^xsd:string ;',
                                    f'\tdici_onto:hasFileName "{value}"^^xsd:string .'
                                ]

                            ts_declarations.extend(ts_lines)
                            ts_declarations.append("")

                        elif time_type == "Live":
                            attr_properties.extend([
                                f"dici_onto:hasLiveTimeSeries {ts_attr_uri}",
                                f'dici_onto:hasLiveTimeSeriesReference "{value}"^^xsd:string'
                            ])

                            if qudt_unit:
                                ts_lines = [
                                    f"{ts_attr_uri} a dici_onto:TimeSeries ;",
                                    f'\tdici_onto:realTimeSource "{value}"^^xsd:string ;',
                                    f'\tqudt:unit <http://qudt.org/vocab/unit/{qudt_unit}> ;',
                                    f'\tdici_onto:hasUnitLabel "{qudt_unit}"^^xsd:string .'
                                ]
                            else:
                                ts_lines = [
                                    f"{ts_attr_uri} a dici_onto:TimeSeries ;",
                                    f'\tdici_onto:realTimeSource "{value}"^^xsd:string .'
                                ]

                            ts_declarations.extend(ts_lines)
                            ts_declarations.append("")

                    # Build the final attribute declaration
                    attr_lines = [f"{single_attr_uri} {attr_properties[0]}"]
                    for prop in attr_properties[1:]:
                        attr_lines.append(f"\t{prop}")

                    # Join with proper semicolons and period
                    formatted_attr = " ;\n".join(attr_lines) + " ."

                    # Add the single attribute and all its time series
                    attribute_value_declarations.append(formatted_attr)
                    attribute_value_declarations.append("")
                    attribute_value_declarations.extend(ts_declarations)

                # Process non-time-based columns (existing logic)
                for col in non_time_cols:
                    attr_type = col[1] if len(col) > 1 else None
                    # Clean up attribute type - remove spaces and handle variations
                    if attr_type:
                        attr_type = attr_type.strip().replace(" ", "")
                        # Filter out pandas "Unnamed" placeholders
                        if attr_type.startswith("Unnamed:") or attr_type.startswith("Unnamed_"):
                            attr_type = None

                    qudt_unit = get_clean_header_value(col, 2, is_nonempty)
                    if not qudt_unit and default_units and attr_name in default_units:
                        qudt_unit = default_units[attr_name]
                        if attr_name not in stamped_default_logged:
                            print(f"[replica-builder] '{attr_name}': no unit in workbook — "
                                  f"stamped ontology default unit:{qudt_unit}")
                            stamped_default_logged.add(attr_name)
                    qudt_unit_y = get_clean_header_value(col, 3, is_nonempty)
                    currency = get_clean_header_value(col, 4, is_nonempty)
                    predicate = get_clean_header_value(col, 5, is_nonempty)  # predicate for class objects

                    # NEW: LinkedClassObjectType - only extract if 7th header exists and value is valid
                    linked_class_type = None
                    if has_7th_header:
                        linked_class_type = get_clean_header_value(col, 6, is_nonempty)

                    value = row[col]
                    if not is_nonempty(value):
                        continue

                    # Generate attribute URI using the new helper function
                    attr_uri = generate_attribute_uri(instance_uri, attr_name, uri_mode)

                    # Handle different attribute types
                    if attr_type == "Annotation":
                        # `rdfs:` is reserved for W3C-defined annotation
                        # properties (label, comment, seeAlso, isDefinedBy).
                        # Pinning an arbitrary column name like `BaseCarrier`
                        # under `rdfs:` produces a syntactically valid but
                        # semantically nonsense IRI — `rdfs:BaseCarrier`
                        # doesn't exist. So:
                        #
                        #  - if the column name matches a valid rdfs:* annotation
                        #    property, emit `rdfs:<name>` (the usual case for
                        #    labels and comments);
                        #  - otherwise emit it under `dici_onto:` (typed by the
                        #    core ontology if a matching annotation property
                        #    exists there) or fall back to the project namespace
                        #    `:<name>` — which is at least a well-formed,
                        #    project-owned IRI.
                        #
                        # The deeper fix is for workbook authors to use the
                        # right attribute type (e.g. `Categorical` for things
                        # like CarrierCategory or BaseCarrier that draw from a
                        # closed vocabulary). Annotation should be reserved
                        # for free-form labels and comments.
                        VALID_RDFS_ANNOTATIONS = {
                            "label", "comment", "seeAlso", "isDefinedBy"
                        }
                        if attr_name in VALID_RDFS_ANNOTATIONS:
                            annotation_lines.append(
                                f'\trdfs:{attr_name} "{str(value).strip()}"'
                            )
                        else:
                            # Project namespace — IRI is well-formed and
                            # project-scoped (https://digicities.info/proj/<P>#name).
                            annotation_lines.append(
                                f'\t:{attr_name} "{str(value).strip()}"'
                            )
                        continue

                    elif attr_type == "ClassObject":
                        # Handle Class Object type - create direct predicate relationship.
                        # ClassObject attributes express entity relationships, not measured quantities,
                        # so no unit label is applicable here.
                        if predicate and is_nonempty(predicate):
                            # Check if LinkedClassObjectType is provided
                            if linked_class_type and is_nonempty(linked_class_type):
                                # LinkedClassObjectType is always a full URI prefix including
                                # its trailing separator (/ or #). Concatenate directly.
                                target_uri = f"<{linked_class_type.strip()}{str(value).strip()}>"
                            else:
                                # Fall back to existing behavior based on uri_mode
                                if uri_mode == "default":
                                    target_uri = f"<{project_uri}/{str(value).strip()}>"
                                elif uri_mode == "full-uri-in-cell":
                                    # Assume the value contains the complete target URI
                                    target_uri = f"<{str(value).strip()}>"
                                elif uri_mode == "complete-project-uri":
                                    # Use the project_uri base with the value
                                    target_uri = f"<{project_uri}{str(value).strip()}>"

                            if predicate == "a":
                                class_object_lines.append(f'\ta {target_uri}')
                            else:
                                class_object_lines.append(f'\tdici_onto:{predicate} {target_uri}')
                        continue

                    elif attr_type == "Identifier":
                        # Handle Identifier type.
                        # Identifiers are string keys with no physical unit, so no unit label needed.
                        identifier_uri = generate_attribute_uri(instance_uri, attr_name, uri_mode)
                        identifier_uris.append(f'\tdici_onto:hasIdentifier {identifier_uri}')

                        # Create the identifier declaration
                        identifier_lines = [
                            f"{identifier_uri} a dici_onto:{attr_name} ;",
                            f'\tdici_onto:identifierValue "{str(value).strip()}" .'
                        ]
                        identifier_declarations.extend(identifier_lines)
                        identifier_declarations.append("")
                        continue

                    elif attr_type == "Resource":
                        # Handle Resource type
                        if attr_uri not in instance_attr_uris:
                            instance_attr_uris.add(attr_uri)
                            attr_uri_list.append(attr_uri)
                        add_specific_attr_uri(sheet_name, attr_name, attr_uri, specific_attr_uri_list)

                        attr_lines = [
                            f"{attr_uri} a dici_onto:{attr_name} ;",
                            f"\ta dici_onto:ResourceAttribute ;",
                            f'\tdici_onto:hasDataPath "{str(value).strip()}"^^xsd:string .'
                        ]
                        attribute_value_declarations.extend(attr_lines)
                        attribute_value_declarations.append("")
                        continue

                    elif attr_type == "SimpleValue":
                        # Handle SimpleValue type - a basic attribute with just a value, NO units.
                        # SimpleValue attributes carry no physical dimension, so no unit label is needed.
                        if attr_uri not in instance_attr_uris:
                            instance_attr_uris.add(attr_uri)
                            attr_uri_list.append(attr_uri)
                        add_specific_attr_uri(sheet_name, attr_name, attr_uri, specific_attr_uri_list)

                        attr_lines = [
                            f"{attr_uri} a dici_onto:{attr_name}",
                            f"a dici_onto:SimpleValueAttribute"
                        ]

                        # Check for datasource
                        ds_col = next((c for c in df.columns if c[0] == f"{attr_name}_datasource"), None)
                        if ds_col:
                            datasource_value = row[ds_col]
                            if datasource_value and is_nonempty(datasource_value):
                                attr_lines.extend(get_datasource_lines(datasource_value, ref_uri_map))

                        # Handle the value - use dici_onto:hasAttributeValue
                        try:
                            numeric_val = float(value)
                            if not math.isnan(numeric_val):
                                decimal_str = format_decimal(numeric_val)
                                attr_lines.append(f'dici_onto:hasAttributeValue "{decimal_str}"^^xsd:decimal')
                            else:
                                attr_lines.append(f'dici_onto:hasAttributeValue "{value}"^^xsd:string')
                        except:
                            attr_lines.append(f'dici_onto:hasAttributeValue "{str(value).strip()}"^^xsd:string')

                        # Format with semicolons and final period
                        formatted_attr = f"{attr_lines[0]} ;\n\t" + " ;\n\t".join(attr_lines[1:]) + " ."
                        attribute_value_declarations.append(formatted_attr)
                        attribute_value_declarations.append("")
                        continue

                    elif attr_type == "CustomPhysicalRatio":
                        # Handle CustomPhysicalRatio type.
                        # Ratio units (e.g. KWh/yr) cannot be expressed as a single qudt:Unit IRI,
                        # so dici_onto:hasUnitLabel is used exclusively here — replacing the previous
                        # invalid qudt:unit literal. The constituent IRIs are constrained at the class
                        # level via dici_onto:hasRatioUnits in the ontology extension.
                        if attr_uri not in instance_attr_uris:
                            instance_attr_uris.add(attr_uri)
                            attr_uri_list.append(attr_uri)
                        add_specific_attr_uri(sheet_name, attr_name, attr_uri, specific_attr_uri_list)

                        attr_lines = []
                        attr_lines.append(f"{attr_uri} a dici_onto:{attr_name} ;")
                        attr_lines.append(f"\ta dici_onto:CustomPhysicalRatioAttribute ;")

                        # Check for datasource
                        ds_col = next((c for c in df.columns if c[0] == f"{attr_name}_datasource"), None)
                        if ds_col:
                            datasource_value = row[ds_col]
                            if datasource_value and is_nonempty(datasource_value):
                                for ds_line in get_datasource_lines(datasource_value, ref_uri_map):
                                    attr_lines.append(f'\t{ds_line} ;')

                        # Add the numeric value
                        try:
                            numeric_val = float(value)
                            if not math.isnan(numeric_val):
                                decimal_str = format_decimal(numeric_val)
                                attr_lines.append(f'\tqudt:value "{decimal_str}"^^xsd:decimal ;')
                            else:
                                attr_lines.append(f'\tqudt:value "{value}"^^xsd:string ;')
                        except:
                            attr_lines.append(f'\tqudt:value "{str(value).strip()}"^^xsd:string ;')

                        # Build the unit label string using dici_onto:hasUnitLabel (DatatypeProperty).
                        # Note: qudt:unit is an ObjectProperty requiring a qudt:Unit IRI — it is NOT
                        # used here because no composite ratio IRI exists in QUDT for arbitrary ratios.
                        if qudt_unit and qudt_unit_y:
                            attr_lines.append(f'\tdici_onto:hasUnitLabel "{qudt_unit}/{qudt_unit_y}" .')
                        elif qudt_unit:
                            attr_lines.append(f'\tdici_onto:hasUnitLabel "{qudt_unit}" .')
                        elif qudt_unit_y:
                            attr_lines.append(f'\tdici_onto:hasUnitLabel "1/{qudt_unit_y}" .')
                        else:
                            # No units: remove trailing semicolon from last line and close
                            attr_lines[-1] = attr_lines[-1].rstrip(" ;") + " ."

                        formatted_attr = "\n".join(attr_lines)
                        attribute_value_declarations.append(formatted_attr)
                        attribute_value_declarations.append("")
                        continue

                    elif attr_type == "Event":
                        # Handle Event type for temporal data.
                        # Events represent points in time, not physical quantities, so no unit label.
                        if attr_uri not in instance_attr_uris:
                            instance_attr_uris.add(attr_uri)
                            attr_uri_list.append(attr_uri)
                        add_specific_attr_uri(sheet_name, attr_name, attr_uri, specific_attr_uri_list)

                        # Convert value to string and handle floats like 1957.0
                        value_str = str(value).strip()

                        # If it's a float that represents a year (e.g., 1957.0), convert to int
                        try:
                            float_val = float(value_str)
                            if float_val.is_integer() and 1000 <= float_val <= 9999:
                                value_str = str(int(float_val))
                        except:
                            pass

                        # Start building attribute lines
                        attr_lines = [
                            f"{attr_uri} a dici_onto:{attr_name}",
                            f"\ta dici_onto:EventAttribute"
                        ]

                        # Try to parse different date formats
                        temporal_value = None
                        temporal_type = None

                        try:
                            # Check for full timestamp (ISO format or similar)
                            if 'T' in value_str or (':' in value_str and len(value_str) > 5):
                                # Try parsing as datetime
                                for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%d.%m.%Y %H:%M:%S']:
                                    try:
                                        dt = datetime.datetime.strptime(value_str, fmt)
                                        temporal_value = dt.strftime('%Y-%m-%dT%H:%M:%S')
                                        temporal_type = "xsd:dateTime"
                                        attr_lines.append(f"\tdici_onto:hasTemporalPrecision dici_onto:DateTime")
                                        break
                                    except:
                                        continue

                            # Check for date with month (MM.YYYY or YYYY-MM or YYYY/MM)
                            elif '.' in value_str or '-' in value_str or '/' in value_str:
                                # Try month.year format (e.g., 07.1970)
                                if re.match(r'^\d{1,2}\.\d{4}$', value_str):
                                    parts = value_str.split('.')
                                    temporal_value = f"{parts[1]}-{parts[0].zfill(2)}"
                                    temporal_type = "xsd:gYearMonth"
                                    attr_lines.append(f"\tdici_onto:hasTemporalPrecision dici_onto:YearMonth")
                                # Try year-month format
                                elif re.match(r'^\d{4}-\d{1,2}$', value_str):
                                    parts = value_str.split('-')
                                    temporal_value = f"{parts[0]}-{parts[1].zfill(2)}"
                                    temporal_type = "xsd:gYearMonth"
                                    attr_lines.append(f"\tdici_onto:hasTemporalPrecision dici_onto:YearMonth")
                                # Try full date (DD.MM.YYYY or YYYY-MM-DD)
                                else:
                                    for fmt in ['%d.%m.%Y', '%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y']:
                                        try:
                                            dt = datetime.datetime.strptime(value_str, fmt)
                                            temporal_value = dt.strftime('%Y-%m-%d')
                                            temporal_type = "xsd:date"
                                            attr_lines.append(f"\tdici_onto:hasTemporalPrecision dici_onto:Date")
                                            break
                                        except:
                                            continue

                            # Check for year only (4 digits)
                            elif re.match(r'^\d{4}$', value_str):
                                temporal_value = value_str
                                temporal_type = "xsd:gYear"
                                attr_lines.append(f"\tdici_onto:hasTemporalPrecision dici_onto:Year")

                            # If we successfully parsed a temporal value
                            if temporal_value and temporal_type:
                                attr_lines.append(f'\tdici_onto:hasTemporalValue "{temporal_value}"^^{temporal_type}')
                            else:
                                # Fallback to string if we can't parse it
                                attr_lines.append(f'\tdici_onto:hasTemporalValue "{value_str}"^^xsd:string')
                                attr_lines.append(f"\tdici_onto:hasTemporalPrecision dici_onto:Unknown")

                        except Exception as e:
                            # If all parsing fails, store as string
                            attr_lines.append(f'\tdici_onto:hasTemporalValue "{value_str}"^^xsd:string')
                            attr_lines.append(f"\tdici_onto:hasTemporalPrecision dici_onto:Unknown")

                        # Check for datasource
                        ds_col = next((c for c in df.columns if c[0] == f"{attr_name}_datasource"), None)
                        if ds_col:
                            datasource_value = row[ds_col]
                            if datasource_value and is_nonempty(datasource_value):
                                for ds_line in get_datasource_lines(datasource_value, ref_uri_map):
                                    attr_lines.append(f'\t{ds_line}')

                        # Properly format the attribute declaration with semicolons and final period
                        attr_lines[-1] = attr_lines[-1] + " ."
                        formatted_attr = " ;\n".join(attr_lines)

                        attribute_value_declarations.append(formatted_attr)
                        attribute_value_declarations.append("")
                        continue

                    elif attr_type == "Categorical":
                        # Handle categorical attributes - use the value as the category type.
                        # Categorical attributes classify instances, not measured quantities,
                        # so no unit label is needed.
                        if attr_uri not in instance_attr_uris:
                            instance_attr_uris.add(attr_uri)
                            attr_uri_list.append(attr_uri)
                        add_specific_attr_uri(sheet_name, attr_name, attr_uri, specific_attr_uri_list)

                        attr_lines = [
                            f"{attr_uri} a dici_onto:{attr_name} ;",
                            f"\ta dici_onto:CategoricalAttribute ;",
                            f"\ta dici_onto:{str(value).strip()} ;"
                            f"\tdici_onto:hasCategoricalValue dici_onto:{str(value).strip()} ."
                        ]
                        attribute_value_declarations.extend(attr_lines)
                        attribute_value_declarations.append("")
                        continue

                    # Add to attribute URI lists for non-time-based attributes
                    if attr_uri not in instance_attr_uris:
                        instance_attr_uris.add(attr_uri)
                        attr_uri_list.append(attr_uri)
                    add_specific_attr_uri(sheet_name, attr_name, attr_uri, specific_attr_uri_list)

                    attr_lines = []

                    # Check for _datasource column
                    ds_col = next((c for c in df.columns if c[0] == f"{attr_name}_datasource"), None)
                    datasource_value = None
                    if ds_col:
                        datasource_value = row[ds_col]

                    if attr_type == "Curve":
                        # Handle Curve type.
                        # xUnit / yUnit (ObjectProperties → qudt:Unit IRI) with their
                        # xUnitLabel / yUnitLabel (DatatypeProperties → xsd:string) alongside,
                        # so applications can read the unit string without resolving QUDT IRIs.
                        #
                        # Both are OPTIONAL and must be omitted when the header row is blank:
                        # interpolating a missing value emitted the literal IRI `unit:None`,
                        # which resolves to nothing and silently poisoned every curve whose
                        # y-unit row was empty — whether deliberately (a dimensionless thrust
                        # coefficient) or by omission upstream.
                        attr_lines.extend([
                            f"{attr_uri} a dici_onto:{attr_name} ;",
                            f"\ta dici_onto:CurveAttribute ;",
                        ])
                        if qudt_unit:
                            attr_lines.append(f"\tdici_onto:xUnit unit:{qudt_unit} ;")
                            attr_lines.append(f'\tdici_onto:xUnitLabel "{qudt_unit}"^^xsd:string ;')
                        if qudt_unit_y:
                            attr_lines.append(f"\tdici_onto:yUnit unit:{qudt_unit_y} ;")
                            attr_lines.append(f'\tdici_onto:yUnitLabel "{qudt_unit_y}"^^xsd:string ;')

                        attr_lines.append('\tdici_onto:hasDataPoints """[')
                        formatted_points = process_curve_data(str(value))
                        attr_lines.extend(formatted_points)
                        attr_lines.append('    ]"""')

                        # Add datasource if present
                        if datasource_value and is_nonempty(datasource_value):
                            ds_lines = get_datasource_lines(datasource_value, ref_uri_map)
                            attr_lines.append(' ;\n\t' + ' ;\n\t'.join(ds_lines) + ' .')
                        else:
                            attr_lines[-1] += ' .'

                    elif attr_type in ["SimpleCost", "UnitBasedCost"]:
                        # Handle cost attributes.
                        # SimpleCost has no physical unit (currency only), so no unit label.
                        # UnitBasedCost carries a QUDT unit IRI; a hasUnitLabel string is added
                        # alongside it for backwards-compatible string access.
                        attr_lines.append(f"{attr_uri} a dici_onto:{attr_name} ;")
                        attr_lines.append(f"\ta dici_onto:{attr_type}Attribute ;")

                        try:
                            numeric_val = float(value)
                            if not math.isnan(numeric_val):
                                decimal_str = format_decimal(numeric_val)
                                attr_lines.append(f'\tqudt:value "{decimal_str}"^^xsd:decimal ;')
                            else:
                                attr_lines.append(f'\tqudt:value "{value}"^^xsd:string ;')
                        except:
                            attr_lines.append(f'\tqudt:value "{value}"^^xsd:string ;')

                        if attr_type == "UnitBasedCost" and qudt_unit:
                            # Preserve existing qudt:unit IRI
                            attr_lines.append(f"\tqudt:unit <http://qudt.org/vocab/unit/{qudt_unit}> ;")
                            # Add string label for backwards-compatible string-based access
                            attr_lines.append(f'\tdici_onto:hasUnitLabel "{qudt_unit}"^^xsd:string ;')

                        # Add datasource if present
                        if datasource_value and is_nonempty(datasource_value):
                            for ds_line in get_datasource_lines(datasource_value, ref_uri_map):
                                attr_lines.append(f"\t{ds_line} ;")

                        if currency:
                            attr_lines.append(f"\tdici_onto:currency cur:{currency} .")
                        else:
                            attr_lines[-1] = attr_lines[-1].rstrip(" ;") + " ."

                    else:
                        # Physical, Geospatial, and any other attr types with a unit dimension.
                        # qudt:unit <IRI> is preserved unchanged for backwards compatibility.
                        # dici_onto:hasUnitLabel is added alongside it so applications can
                        # access the unit as a plain string (e.g. SPARQL query without QUDT vocab).
                        attr_lines.append(f"{attr_uri} a dici_onto:{attr_name} ;")

                        # Add the attribute type if specified, always with "Attribute" suffix
                        if attr_type:
                            attr_lines.append(f"\ta dici_onto:{attr_type}Attribute ;")

                        if qudt_unit:
                            # Preserve the existing IRI-based unit triple
                            attr_lines.append(f"\tqudt:unit <http://qudt.org/vocab/unit/{qudt_unit}> ;")
                            # Add human-readable string label alongside the IRI
                            attr_lines.append(f'\tdici_onto:hasUnitLabel "{qudt_unit}"^^xsd:string ;')

                        # Add datasource if present
                        if datasource_value and is_nonempty(datasource_value):
                            for ds_line in get_datasource_lines(datasource_value, ref_uri_map):
                                attr_lines.append(f"\t{ds_line} ;")

                        try:
                            numeric_val = float(value)
                            if not math.isnan(numeric_val):
                                decimal_str = format_decimal(numeric_val)
                                attr_lines.append(f'\tqudt:value "{decimal_str}"^^xsd:decimal ;')
                            else:
                                attr_lines.append(f'\tqudt:value "{value}"^^xsd:string ;')
                        except:
                            attr_lines.append(f'\tqudt:value "{value}"^^xsd:string ;')

                        attr_lines[-1] = attr_lines[-1].rstrip(" ;") + " ."

                    attribute_value_declarations.extend(attr_lines)
                    attribute_value_declarations.append("")

            # Create the instance block
            if annotation_lines:
                instance_lines.extend(annotation_lines)
            if class_object_lines:
                instance_lines.extend(class_object_lines)
            if identifier_uris:
                instance_lines.extend(identifier_uris)
            if attr_uri_list:
                instance_lines.append("\tdici_onto:hasAttribute " + ",\n\t".join(attr_uri_list))
            instance_declarations.append(" ;\n".join(instance_lines) + " .")

            if specific_attr_uri_list:
                specific_str = f"\n{instance_uri} " + ";\n\t".join(specific_attr_uri_list) + "."
                instance_declarations.append(specific_str)

            instance_declarations.append("")

    # Combine everything in the correct order: prefixes, references, instance declarations, attribute values
    ttl_lines.extend(reference_declarations)
    ttl_lines.extend(instance_declarations)
    ttl_lines.extend(attribute_value_declarations)
    ttl_lines.extend(identifier_declarations)

    # Write TTL file
    with open(output_ttl_path, "w", encoding="utf-8") as f:
        f.write("\n".join(ttl_lines))

    # Validate with rdflib
    g = rdflib.Graph()
    try:
        g.parse(output_ttl_path, format="turtle")
        print(f"TTL file successfully created and validated: {output_ttl_path}")
        print(f"URI mode used: {uri_mode}")
    except Exception as e:
        print("Warning: Errors were detected in the output TTL:", e)


