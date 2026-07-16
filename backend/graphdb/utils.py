# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""Pure helper functions for parsing SPARQL responses and handling RDF graphs."""

import datetime

import pandas as pd
import rdflib


def df_from_json(query_out):
    """Convert SPARQL JSON response to pandas DataFrame"""
    cols = query_out["head"]["vars"]

    out = []
    for row in query_out["results"]["bindings"]:
        item = []
        for c in cols:
            item.append(row.get(c, {}).get("value"))
        out.append(item)

    df = pd.DataFrame(out, columns=cols)
    return df


def dict_from_json(query_out):
    """Generate a dictionary from a SPARQL query response with only one row"""
    rows_dict = {}

    i = 0
    for row in query_out["results"]["bindings"]:
        rows_dict.update(row)
        i += 1
        if i == 2:
            raise ValueError(
                "dict_from_json function not intended to use with queries that yield more than one row"
            )

    dict_out = {}
    for key, value in rows_dict.items():
        if value.get("datatype") == "http://www.w3.org/2001/XMLSchema#boolean":
            if value["value"] == "true":
                value["value"] = True
            elif value["value"] == "false":
                value["value"] = False
        dict_out[key] = value["value"]

    return dict_out


def split_graph(graph, split_size):
    """
    Split a graph into subgraphs to make uploading via API possible.

    Args:
        graph: An rdflib graph
        split_size: The number of triples to be stored in each split

    Returns:
        A list of the subgraphs
    """
    subgraphs = []
    triples_list = list(graph.triples((None, None, None)))

    for i in range(0, len(triples_list), split_size):
        subgraph = rdflib.Graph()
        for triple in triples_list[i: i + split_size]:
            subgraph.add(triple)
        subgraphs.append(subgraph)

    return subgraphs


def save_debug_report(debug_report, output_file="debug_report.txt"):
    """
    Save the debug report to a file.

    Args:
        debug_report (dict): Debug report from upload_ttl with debug_mode=True
        output_file (str): Path to save the debug report
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=== GRAPHDB UPLOAD DEBUG REPORT ===\n")
        f.write(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Graph Name: {debug_report['graph_name']}\n")
        f.write(f"Total Triples: {debug_report['total_triples']}\n")
        f.write(f"Successful: {debug_report['successful_count']}\n")
        f.write(f"Failed: {debug_report['failed_count']}\n")
        f.write(f"Success Rate: {debug_report['success_rate']:.2f}%\n")
        f.write("\n" + "=" * 50 + "\n")

        if debug_report['failed_triples']:
            f.write("FAILED TRIPLES:\n")
            f.write("-" * 50 + "\n")

            for i, failed in enumerate(debug_report['failed_triples'], 1):
                f.write(f"\nFailed Triple #{i} (Index: {failed['triple_index']}):\n")
                f.write(f"Triple: {failed['triple_str']}\n")
                f.write(f"Error Type: {failed['error_type']}\n")

                if 'error_message' in failed:
                    f.write(f"Error Message: {failed['error_message']}\n")
                if 'status_code' in failed:
                    f.write(f"HTTP Status: {failed['status_code']}\n")
                if 'response_text' in failed:
                    f.write(f"Response: {failed['response_text']}\n")
                f.write("-" * 30 + "\n")
        else:
            f.write("No failed triples - all uploads successful!\n")

    print(f"Debug report saved to: {output_file}")
