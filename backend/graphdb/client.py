# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
Pure Python GraphDB client.

Supports three authentication modes:
  - ``no_auth``     — local dev (AUTH_DISABLED=true); no Authorization header
  - ``token``       — pre-issued bearer token (Streamlit / Keycloak flow)
  - ``credentials`` — username/password, exchanges for a token directly

Integrations that need UI-level error handling or token refresh (e.g. the
Streamlit shell at ``components/graphdb.py``) inject those concerns via the
``token_refresher`` callback and the ``_on_query_error`` hook.
"""

import json
import os
import time
import urllib.parse
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import rdflib
import requests

from backend.graphdb.utils import df_from_json, dict_from_json, split_graph


TokenRefresher = Callable[[], Optional[str]]


class UnifiedGraphDBClient:
    """
    GraphDB client supporting token, username/password, and no-auth modes,
    with retry/reconnection and clear error handling.
    """

    default_graph_name = "<https://digicities.info>"

    def __init__(
        self,
        token=None,
        selected_repo=None,
        username=None,
        password=None,
        repository=None,
        base_url=None,
        max_retries=3,
        token_refresher: Optional[TokenRefresher] = None,
    ):
        """
        Args:
            token: Bearer token for authentication (Streamlit app mode).
                Pass ``"local"`` or ``""`` to enable no-auth mode.
            selected_repo: Repository name for token auth.
            username: Username for basic auth (legacy mode).
            password: Password for basic auth (legacy mode).
            repository: Repository name for basic auth (legacy mode).
            base_url: GraphDB base URL. Defaults to ``GRAPHDB_URL`` env var.
            max_retries: Maximum number of retry attempts.
            token_refresher: Optional callable invoked when a token-mode
                session's access token expires or is rejected. Should return
                a fresh bearer token string (without the ``Bearer `` prefix)
                or ``None`` if no refresh is possible.
        """
        self.max_retries = max_retries
        self.retry_delay = 1  # seconds
        self.session = None
        self._token_refresher = token_refresher

        # Determine authentication mode
        if token == "local" or token == "":
            # No-auth mode for local development (AUTH_DISABLED=true)
            self.auth_mode = "no_auth"
            self.token = None
            self.selected_repo = selected_repo or repository or "digicities"
            self.repository = self.selected_repo
            self.base_url = base_url or os.getenv("GRAPHDB_URL", "http://localhost:7200")
            self.GraphDB_url = self.base_url
        elif token and selected_repo:
            # Token-based authentication (Streamlit app)
            self.auth_mode = "token"
            self.token = token
            self.selected_repo = selected_repo
            self.repository = selected_repo  # For compatibility
            self.base_url = base_url or os.getenv("GRAPHDB_URL", "http://localhost:7200")
            self.GraphDB_url = self.base_url  # For compatibility
        elif username and password and repository:
            # Username/password authentication (legacy)
            self.auth_mode = "credentials"
            self.username = username
            self.password = password
            self.repository = repository
            self.selected_repo = repository  # For compatibility
            self.GraphDB_url = os.getenv("GRAPHDB_URL", "http://localhost:7200")
            self.base_url = self.GraphDB_url
        else:
            raise ValueError(
                "Either (token, selected_repo) or (username, password, repository) must be provided"
            )

        self._initialize_auth()

        print(f"UnifiedGraphDBClient successfully initialized in {self.auth_mode} mode.")

    def _initialize_auth(self):
        """Initialize authentication based on the mode"""
        if self.auth_mode == "no_auth":
            self.access_token = None
            self.token_time = time.time()
        elif self.auth_mode == "token":
            self._create_token_session()
        else:
            self.get_access_token()

        self._create_session()

    def _create_token_session(self):
        """Create session for token-based auth"""
        self.access_token = f"Bearer {self.token}"
        self.token_time = time.time()

    def get_access_token(self):
        """
        Get access token for username/password auth.

        Two flows are supported:
          1. Keycloak (or any OIDC provider): configure ``KEYCLOAK_TOKEN_URL``
             in the environment. The client POSTs username/password with
             ``grant_type=password`` and expects an ``access_token`` in the
             JSON response.
          2. GraphDB built-in auth: if ``KEYCLOAK_TOKEN_URL`` is unset, the
             client falls back to GraphDB's ``/rest/login/{username}`` endpoint,
             which returns an Authorization header directly.
        """
        token_url = os.getenv("KEYCLOAK_TOKEN_URL")
        oidc_client_id = os.getenv("KEYCLOAK_CLIENT_ID", "graphdb")

        if token_url:
            payload = (
                f"client_id={oidc_client_id}"
                f"&username={self.username}"
                f"&password={self.password}"
                f"&grant_type=password&scope=openid"
            )
            headers = {"Content-Type": "application/x-www-form-urlencoded"}

            response = requests.request("POST", token_url, headers=headers, data=payload)
            response.raise_for_status()

            retrieved_access_token = response.json()["access_token"]
            self.access_token = f"Bearer {retrieved_access_token}"
        else:
            url = f"{self.GraphDB_url}/rest/login/{self.username}"

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-GraphDB-Password": self.password,
            }

            response = requests.request("POST", url, headers=headers)
            response.raise_for_status()
            self.access_token = response.headers["Authorization"]

        self.token_time = time.time()
        print("GraphDB access token retrieved")

        return self.access_token

    def check_access_token_time_valid(self, renew=True):
        """Check if access token is still valid (expires after 8 hours)"""
        if self.auth_mode == "no_auth":
            return True

        if not hasattr(self, "access_token"):
            raise KeyError("GraphDBClient still has not retrieved an access token")

        if (time.time() - self.token_time) / 3600 > 7.99:
            if renew:
                if self.auth_mode == "token":
                    self._refresh_token_and_session()
                else:
                    self.get_access_token()
            return False
        else:
            return True

    def _create_session(self):
        """Create a new requests session with proper headers"""
        self.session = requests.Session()
        headers = {
            'Accept': 'application/sparql-results+json',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        if self.access_token:
            headers['Authorization'] = self.access_token
        self.session.headers.update(headers)

    def _log_debug(self, message: str):
        """Log debug messages"""
        print(f"DEBUG [GraphDB]: {message}")

    def _on_query_error(self, message: str, query: str) -> None:
        """
        Hook called when a query fails after all retries.

        Subclasses (e.g. the Streamlit shell) can override this to surface
        the error in a UI. The default is a no-op — the error is already
        logged via ``_log_debug``.
        """
        return None

    def _is_auth_error(self, response) -> bool:
        return response.status_code in [401, 403]

    def _is_server_error(self, response) -> bool:
        return response.status_code >= 500

    def _refresh_token_and_session(self):
        """Attempt to refresh the token and create a new session."""
        self._log_debug("Attempting to refresh token and session")

        if self.auth_mode == "no_auth":
            return False

        if self.auth_mode == "token":
            if self._token_refresher is None:
                self._log_debug("No token_refresher configured; cannot refresh token-mode session")
                return False
            try:
                new_token = self._token_refresher()
            except Exception as e:
                self._log_debug(f"token_refresher raised: {e}")
                return False
            if not new_token:
                self._log_debug("token_refresher returned no token")
                return False
            self.token = new_token
            self._create_token_session()
            self._create_session()
            self._log_debug("Token and session refreshed via token_refresher")
            return True

        # credentials mode
        try:
            self.get_access_token()
            self._create_session()
            self._log_debug("Token refreshed with credentials")
            return True
        except Exception as e:
            self._log_debug(f"Failed to refresh with credentials: {e}")
            return False

    def _triplestore(self):
        """Return the active triplestore backend (lazily imported to avoid a
        backend.triplestore → backend.graphdb circular dependency at import
        time). Used to construct backend-correct URLs for SPARQL ops."""
        from backend.triplestore import get_backend
        return get_backend()

    def _query_url(self, query_str: str) -> str:
        return f"{self._triplestore().query_url(self.repository)}?query={urllib.parse.quote(query_str)}"

    def _update_url(self, update_str: str) -> str:
        return f"{self._triplestore().update_url(self.repository)}?update={urllib.parse.quote(update_str)}"

    def _graph_store_url(self, graph_name: Optional[str] = None) -> str:
        """URL for SPARQL Graph Store HTTP Protocol uploads. graph_name is the
        already-quoted graph IRI (callers pass it after urllib.parse.quote)."""
        backend = self._triplestore()
        if graph_name:
            # Defensively re-decode then re-encode via the backend's helper so
            # both legacy ?context= callers and new ?graph= callers work right.
            try:
                graph_iri = urllib.parse.unquote(graph_name)
            except Exception:
                graph_iri = graph_name
            # Tolerate callers that pass the SPARQL `<iri>` form — the Graph
            # Store Protocol wants the bare IRI, not the angle-bracketed one
            # (otherwise the brackets get encoded into the IRI and the server
            # rejects it with HTTP 400).
            graph_iri = graph_iri.strip()
            if graph_iri.startswith("<") and graph_iri.endswith(">"):
                graph_iri = graph_iri[1:-1]
            return backend.graph_store_url(self.repository, graph_iri)
        # No specific graph → default graph endpoint.
        if backend.name == "fuseki":
            return f"{self.base_url}/{self.repository}/data?default"
        return f"{self.base_url}/repositories/{self.repository}/statements"

    def execute_query(self, query: str, infer: bool = True) -> Optional[List[Dict[str, Any]]]:
        """
        Execute a SPARQL query with automatic retry and error handling.
        (Interface for component explorer.)
        """
        result = self.sparql_api_query(query, infer=infer, out_format="response")
        if result and hasattr(result, 'json'):
            try:
                json_data = result.json()
                return json_data.get('results', {}).get('bindings', [])
            except Exception:
                return None
        return None

    def sparql_api_query(self, query, infer=True, out_format="df", replace_namespaces=False):
        """Execute SPARQL query with resilient error handling."""
        out_format_options = ["df", "dict", "response"]
        if out_format not in out_format_options:
            raise ValueError(
                f"'out_format' must be one of {out_format_options}. Passed value: {out_format}"
            )

        # Backend-aware URL: GraphDB uses /repositories/<n>, Fuseki uses /<n>/query.
        # `infer` is a GraphDB-specific query-string flag; Fuseki ignores it harmlessly.
        url = f"{self._query_url(query)}&infer={infer}"

        self._log_debug(f"Executing query on repository: {self.repository}")
        self._log_debug(f"Query: {query[:200]}..." if len(query) > 200 else f"Query: {query}")

        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    self._log_debug(f"Retry attempt {attempt}/{self.max_retries}")
                    time.sleep(self.retry_delay * attempt)

                self.check_access_token_time_valid(renew=True)

                payload = {}
                headers = {"Accept": "application/sparql-results+json"}
                if self.access_token:
                    headers["Authorization"] = self.access_token

                response = requests.request("GET", url, headers=headers, data=payload, timeout=30)

                self._log_debug(f"Response status: {response.status_code}")

                if response.status_code == 200:
                    try:
                        if out_format == "df":
                            result = df_from_json(response.json())
                            if replace_namespaces:
                                result = self.replace_namespaces(result)
                        elif out_format == "dict":
                            result = dict_from_json(response.json())
                        elif out_format == "response":
                            result = response

                        self._log_debug("Query successful")
                        return result
                    except json.JSONDecodeError as e:
                        self._log_debug(f"JSON decode error: {e}")
                        last_exception = e
                        continue

                elif self._is_auth_error(response):
                    self._log_debug(f"Authentication error: {response.status_code}")

                    if attempt == 0 and self._refresh_token_and_session():
                        self._log_debug("Token refreshed, retrying...")
                        continue
                    else:
                        raise requests.exceptions.HTTPError(
                            f"Authentication failed: {response.status_code}"
                        )

                elif self._is_server_error(response):
                    self._log_debug(f"Server error: {response.status_code}, will retry")
                    last_exception = requests.exceptions.HTTPError(
                        f"Server error: {response.status_code}"
                    )
                    continue

                else:
                    self._log_debug(f"Client error: {response.status_code}")
                    self._log_debug(f"Response content: {response.text[:500]}")
                    response.raise_for_status()

            except requests.exceptions.Timeout as e:
                self._log_debug(f"Request timeout on attempt {attempt + 1}")
                last_exception = e
                if attempt < self.max_retries:
                    continue

            except requests.exceptions.ConnectionError as e:
                self._log_debug(f"Connection error on attempt {attempt + 1}: {e}")
                last_exception = e
                if attempt < self.max_retries:
                    continue

            except requests.exceptions.RequestException as e:
                self._log_debug(f"Request exception: {e}")
                last_exception = e
                break

        error_msg = f"Query failed after {self.max_retries + 1} attempts"
        if last_exception:
            error_msg += f": {str(last_exception)}"

        self._log_debug(error_msg)
        self._on_query_error(error_msg, query)

        return None

    def sparql_update(self, statement):
        """Execute a SPARQL update statement (backend-aware URL).

        The update is sent form-encoded in the request body (``update=<stmt>``),
        per the SPARQL 1.1 Protocol. Passing it as a ``?update=`` URL query
        parameter with an empty body is accepted by Fuseki/GraphDB with HTTP 200
        but silently does nothing, so the body form is required.
        """
        url = self._triplestore().update_url(self.repository)

        self.check_access_token_time_valid(renew=True)
        headers = {
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if self.access_token:
            headers["Authorization"] = self.access_token

        # SPARQL update is a write — Fuseki requires Basic auth for it.
        backend_auth = getattr(self._triplestore(), "auth", None)
        response = requests.post(
            url, headers=headers, data={"update": statement}, auth=backend_auth
        )
        response.raise_for_status()

        return response

    def upload_ttl(
            self,
            ttl_str=None,
            ttl_file_path=None,
            graph_name=None,
            replace_existing=False,
            split_size=None,
            debug_mode=False,
    ):
        """
        Upload TTL data to GraphDB repository.

        Args:
            ttl_str: TTL data as string
            ttl_file_path: Path to TTL file
            graph_name: Target graph name
            replace_existing: Whether to replace existing data
            split_size: Size of splits for large uploads
            debug_mode: If True, uploads individual triples and catches errors

        Returns:
            dict: Response information including failed triples if debug_mode=True
        """
        if (ttl_str is None and ttl_file_path is None) or (
                ttl_str is not None and ttl_file_path is not None
        ):
            raise ValueError(
                "One and only one of ttl_str or ttl_file_path must be provided."
            )

        if graph_name:
            # Backend-aware Graph Store URL (GraphDB ?context=, Fuseki ?graph=).
            url = self._graph_store_url(urllib.parse.quote(graph_name))
        else:
            # Default graph upload.
            url = self._graph_store_url(None)

        self.check_access_token_time_valid(renew=True)
        headers = {
            "Content-Type": "text/turtle",
            "Accept": "application/json",
        }
        if self.access_token:
            headers["Authorization"] = self.access_token

        # Fuseki requires HTTP Basic auth for writes via the Graph Store
        # Protocol; GraphDB Free is usually unauthenticated locally. Pass the
        # active backend's credentials so uploads aren't rejected with 401.
        backend_auth = getattr(self._triplestore(), "auth", None)

        if replace_existing:
            request_type = "PUT"
        else:
            request_type = "POST"

        graph = rdflib.Graph()
        if ttl_file_path is not None:
            graph.parse(source=ttl_file_path)
        else:
            graph.parse(data=ttl_str, format="turtle")

        if debug_mode:
            return self._upload_with_debug(graph, url, headers, request_type, graph_name, backend_auth)

        if split_size is not None:
            graph_splits = split_graph(graph=graph, split_size=split_size)
            for graph_split_i in graph_splits:
                serialized_graph = graph_split_i.serialize(
                    format="turtle", encoding="utf-8"
                )

                print(serialized_graph)
                response = requests.request(
                    request_type, url, headers=headers, data=serialized_graph,
                    auth=backend_auth,
                )
                response.raise_for_status()

                if response.ok:
                    print(
                        f"part of splitted graph uploaded successfully (split_size = {split_size} triples)"
                    )
                    request_type = "POST"
                else:
                    print("upload failed, check response log")

            print(
                f"{len(list(graph.subjects()))} triples uploaded to {graph_name}>"
            )
        else:
            if ttl_file_path is not None:
                serialized_graph = graph.serialize(
                    format="turtle", encoding="utf-8"
                )
            else:
                serialized_graph = ttl_str

            response = requests.request(
                request_type, url, headers=headers, data=serialized_graph,
                auth=backend_auth,
            )
            response.raise_for_status()

            # Any 2xx is success. Fuseki returns 200/201 for a Graph Store
            # PUT/POST; GraphDB returns 204. (raise_for_status above already
            # covers the non-2xx case.)
            if response.ok:
                print("data uploaded successfully")
            else:
                print("upload failed, check response log")

        return response

    def _upload_with_debug(self, graph, url, headers, request_type, graph_name, backend_auth=None):
        """Upload triples one at a time, collecting per-triple failure info."""
        failed_triples = []
        successful_count = 0
        total_triples = len(graph)

        print(f"DEBUG MODE: Starting upload of {total_triples} individual triples...")

        for i, triple in enumerate(graph):
            print(f"Processing triple {i + 1}/{total_triples}: {triple[0]} {triple[1]} {triple[2]}")

            try:
                temp_graph = rdflib.Graph()
                temp_graph.add(triple)

                serialized_triple = temp_graph.serialize(format="turtle", encoding="utf-8")

                response = requests.request(
                    "POST",
                    url,
                    headers=headers,
                    data=serialized_triple,
                    auth=backend_auth,
                )
                response.raise_for_status()

                if response.status_code == 204:
                    successful_count += 1
                    if (i + 1) % 100 == 0:
                        print(f"DEBUG MODE: Processed {i + 1}/{total_triples} triples ({successful_count} successful)")
                else:
                    failed_info = {
                        'triple': triple,
                        'triple_str': f"{triple[0]} {triple[1]} {triple[2]} .",
                        'error_type': 'unexpected_status_code',
                        'status_code': response.status_code,
                        'response_text': response.text,
                        'triple_index': i
                    }
                    failed_triples.append(failed_info)
                    print(f"DEBUG MODE: Triple {i} failed with status {response.status_code}")

            except Exception as e:
                failed_info = {
                    'triple': triple,
                    'triple_str': f"{triple[0]} {triple[1]} {triple[2]} .",
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                    'triple_index': i
                }
                failed_triples.append(failed_info)
                print(f"DEBUG MODE: Triple {i} failed with error: {type(e).__name__}: {str(e)}")
                continue

        debug_report = {
            'total_triples': total_triples,
            'successful_count': successful_count,
            'failed_count': len(failed_triples),
            'success_rate': (successful_count / total_triples) * 100 if total_triples > 0 else 0,
            'failed_triples': failed_triples,
            'graph_name': graph_name
        }

        print("\nDEBUG MODE COMPLETE:")
        print(f"Total triples: {total_triples}")
        print(f"Successful: {successful_count}")
        print(f"Failed: {len(failed_triples)}")
        print(f"Success rate: {debug_report['success_rate']:.2f}%")

        if failed_triples:
            print("\nFailed triples summary:")
            error_types = {}
            for failed in failed_triples:
                error_type = failed['error_type']
                error_types[error_type] = error_types.get(error_type, 0) + 1

            for error_type, count in error_types.items():
                print(f"  {error_type}: {count} triples")

        return debug_report

    def upload_rdf_file(
            self,
            rdf_file_path,
            graph_name=None,
            replace_existing=False,
    ):
        """Upload an RDF file to GraphDB."""
        if graph_name:
            graph_name_parsed = urllib.parse.quote(graph_name)
        else:
            graph_name_parsed = urllib.parse.quote(
                UnifiedGraphDBClient.default_graph_name
            )
        # Backend-aware Graph Store URL.
        url = self._graph_store_url(graph_name_parsed)

        self.check_access_token_time_valid(renew=True)
        headers = {
            "Content-Type": "application/xhtml+xml",
            "Accept": "application/json",
        }
        if self.access_token:
            headers["Authorization"] = self.access_token

        # Fuseki requires HTTP Basic auth for writes; use the active backend's creds.
        backend_auth = getattr(self._triplestore(), "auth", None)

        if replace_existing:
            request_type = "PUT"
        else:
            request_type = "POST"

        with open(rdf_file_path, "rb") as rdf_file:
            response = requests.request(
                request_type, url, headers=headers, data=rdf_file, auth=backend_auth
            )

        if response.status_code == 413:
            print(f"{rdf_file_path}: File too large, attempting piecing it up")
            self.upload_ttl(
                ttl_file_path=rdf_file_path,
                graph_name=graph_name,
                replace_existing=replace_existing,
                split_size=10000,
            )
        else:
            response.raise_for_status()

        return response

    def begin_transaction(self):
        """Begin a GraphDB transaction."""
        return Transaction(self)

    def get_named_graph_contents_rest(self, graph_uri="http://scenarios/wind_forecasting",
                                      return_format="df",
                                      save_to_file=False,
                                      file_path=None,
                                      file_format="turtle"):
        """
        Retrieve all triples from a specified named graph via the REST API.

        Args:
            graph_uri (str): URI of the named graph to query
            return_format (str): "df" or "string"
            save_to_file (bool): Whether to save the triples to a file
            file_path (str): Path to save the file. Required if save_to_file is True
            file_format (str): "turtle", "xml", "nt", "json-ld"
        """
        valid_return_formats = ["df", "string"]
        if return_format not in valid_return_formats:
            raise ValueError(f"'return_format' must be one of {valid_return_formats}")

        valid_file_formats = ["turtle", "xml", "nt", "json-ld"]
        if file_format not in valid_file_formats:
            raise ValueError(f"'file_format' must be one of {valid_file_formats}")

        if save_to_file and file_path is None:
            raise ValueError("'file_path' must be specified when 'save_to_file' is True")

        # Backend-aware Graph Store URL for download. GraphDB uses ?context=,
        # Fuseki uses ?graph=. The params dict below is reset accordingly.
        url = self._graph_store_url(None).split("?")[0]

        self.check_access_token_time_valid(renew=True)

        graph_param = "context" if self._triplestore().name == "graphdb" else "graph"
        params = {graph_param: f"<{graph_uri}>"}

        format_map = {
            "application/n-triples": "nt",
            "text/turtle": "turtle",
            "application/rdf+xml": "xml",
            "application/ld+json": "json-ld"
        }

        formats_to_try = list(format_map.items())

        result_graph = None
        raw_content = None

        for content_type, rdf_format in formats_to_try:
            headers = {"Accept": content_type}
            if self.access_token:
                headers["Authorization"] = self.access_token

            try:
                response = requests.request("GET", url, headers=headers, params=params)
                response.raise_for_status()

                raw_content = response.content

                g = rdflib.Graph()
                g.parse(data=raw_content, format=rdf_format)

                if len(g) > 0:
                    result_graph = g
                    print(f"Successfully retrieved graph data using {content_type}")
                    break
                else:
                    print(f"No triples found in the graph using {content_type}")
            except Exception as e:
                print(f"Error with {content_type}: {str(e)}")
                continue

        if result_graph is None:
            print("Failed to retrieve graph data in any supported format")
            if return_format == "df":
                return pd.DataFrame(columns=["subject", "predicate", "object"])
            else:
                return ""

        if save_to_file:
            try:
                import os
                os.makedirs(os.path.dirname(file_path), exist_ok=True)

                result_graph.serialize(destination=file_path, format=file_format)
                print(f"Graph data saved to {file_path} in {file_format} format")
            except Exception as e:
                print(f"Error saving file: {str(e)}")

        if return_format == "df":
            triples = []
            for s, p, o in result_graph:
                triples.append([str(s), str(p), str(o)])

            return pd.DataFrame(triples, columns=["subject", "predicate", "object"])
        else:
            serialized_result = result_graph.serialize(format=file_format)

            if isinstance(serialized_result, bytes):
                return serialized_result.decode('utf-8')
            else:
                return serialized_result

    def test_connection(self) -> bool:
        """Test the connection to GraphDB."""
        test_query = "SELECT (COUNT(*) as ?count) WHERE { ?s ?p ?o } LIMIT 1"
        result = self.sparql_api_query(test_query, out_format="response")
        return result is not None and result.status_code == 200

    def get_repository_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current repository."""
        try:
            url = f"{self.base_url}/repositories/{self.repository}"
            self.check_access_token_time_valid(renew=True)
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            self._log_debug(f"Failed to get repository info: {e}")
        return None

    def get_namespaces(self):
        """Get namespaces from the repository."""
        url = f"{self.base_url}/repositories/{self.repository}/namespaces"

        self.check_access_token_time_valid(renew=True)

        payload = {}
        headers = {"Accept": "application/sparql-results+json"}
        if self.access_token:
            headers["Authorization"] = self.access_token
        response = requests.request("GET", url, headers=headers, data=payload)
        response.raise_for_status()

        namespace_df = df_from_json(response.json())
        namespace_df["prefix"] = namespace_df["prefix"] + ":"

        self.namespaces = namespace_df.set_index("namespace")["prefix"].to_dict()

        return namespace_df

    def replace_namespaces(self, df):
        """Replace URI parts with namespace prefixes."""
        if not hasattr(self, "namespaces"):
            self.get_namespaces()
        df = df.replace(self.namespaces, regex=True)
        return df


class Transaction:
    """Manage a GraphDB transaction."""

    allowed_actions = [
        "ADD",
        "DELETE",
        "GET",
        "UPDATE",
        "SIZE",
        "COMMIT",
        "QUERY",
    ]

    def __init__(self, graph_db_client):
        """
        Args:
            graph_db_client: The GraphDB client with which to start the transaction
        """
        self.graph_db_client = graph_db_client

        url = f"{graph_db_client.base_url}/repositories/{graph_db_client.repository}/transactions"

        graph_db_client.check_access_token_time_valid(renew=True)
        headers = {"Content-Type": "application/json"}
        if graph_db_client.access_token:
            headers["Authorization"] = graph_db_client.access_token

        response = requests.request("POST", url, headers=headers)

        self.location = response.headers["location"]

        print(f"Began transaction process with location: \n {self.location}")

    def execute_action(self, action, update_statement=None):
        if action not in Transaction.allowed_actions:
            raise ValueError(
                f"'action' must be one of {Transaction.allowed_actions}"
            )

        url = self.location
        url += f"?action={action}"
        if action == "UPDATE" and update_statement is not None:
            update_statement = urllib.parse.quote(update_statement)
            update_statement = update_statement.replace("%0A", "")
            url += f"&update={update_statement}"

            print(f"Length of update statement: {len(update_statement)}")
        elif action == "COMMIT":
            pass
        else:
            raise NotImplementedError()

        self.graph_db_client.check_access_token_time_valid(renew=True)
        headers = {"Content-Type": "application/rdf+xml"}
        if self.graph_db_client.access_token:
            headers["Authorization"] = self.graph_db_client.access_token

        response = requests.request("PUT", url, headers=headers)
        response.raise_for_status()

        print(f"Successfully executed {action} action")

    def delete(self):
        """Roll back the transaction and close it."""
        url = self.location

        self.graph_db_client.check_access_token_time_valid(renew=True)
        headers = {"Content-Type": "application/json"}
        if self.graph_db_client.access_token:
            headers["Authorization"] = self.graph_db_client.access_token

        response = requests.request("DELETE", url, headers=headers)
        response.raise_for_status()

        print(f"Successfully deleted transaction with location {self.location}")


class GraphDBClient(UnifiedGraphDBClient):
    """Backward-compatible alias for ``UnifiedGraphDBClient``."""

    def __init__(self, token=None, selected_repo=None, username=None, password=None, repository=None, **kwargs):
        super().__init__(
            token=token,
            selected_repo=selected_repo,
            username=username,
            password=password,
            repository=repository,
            **kwargs
        )
