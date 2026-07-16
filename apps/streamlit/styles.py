# SPDX-License-Identifier: Apache-2.0
# Copyright © 2026, Empa, James Allan, Reto Fricker

"""
CSS Styles for the Digicities Platform
Separated from app.py for cleaner code organization
"""

def get_platform_styles() -> str:
    """
    Get all CSS styles for the Digicities Platform

    Returns:
        str: Complete CSS styling for the platform
    """
    return """
    <style>
        /* Theme: the app follows Streamlit's theme — a light default is pinned in
           .streamlit/config.toml, and users can switch to Dark or "Use system
           setting" from the ⋮ menu (top-right) → Settings. We deliberately do NOT
           force a background colour here: forcing white while the viewer was in
           dark mode is what made text unreadable (notably on macOS). */

        /* Hide the Streamlit footer + top toolbar/header for a clean look.
           Theme switching is handled by our own sidebar "Appearance" control
           (Streamlit 1.59 removed the native theme toggle from that menu), so the
           header doesn't need to be visible. */
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .stSpinner > div {display: none;}

        /* But keep the sidebar collapse/expand controls usable — they live in
           the header we just hid, so without this a collapsed sidebar can never
           be reopened (no visible arrow). Force them visible above everything.
           stExpandSidebarButton is the floating "open sidebar" arrow shown when
           the sidebar is collapsed (Streamlit 1.57). */
        [data-testid="stExpandSidebarButton"],
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"],
        button[aria-label="Open sidebar"],
        button[aria-label="Close sidebar"] {
            visibility: visible !important;
            display: flex !important;
            opacity: 1 !important;
            z-index: 1000000 !important;
        }

        /* Prevent gray overlay during rerun - smoother transitions */
        .stApp > div[data-testid="stAppViewContainer"] > div.main > div {
            transition: opacity 0.1s ease-in-out;
        }
        
        /* Hide content during loading to prevent gray overlay */
        .loading-hidden {
            display: none !important;
        }
        
        /* Smooth module transitions */
        .module-content {
            transition: all 0.2s ease-in-out;
        }

        /* Header layout styles */
        .main-header {
            display: flex;
            align-items: center;
            padding: 1rem 0;
            margin-bottom: 1rem;
        }

        .logo-container {
            flex: 0 0 auto;
            margin-right: 2rem;
        }

        .title-container {
            flex: 1;
            display: flex;
            align-items: center;
        }

        /* Navigation bar logo styling */
        .nav-logo {
            width: 100%;
            margin-bottom: 1rem;
            cursor: pointer;
            transition: opacity 0.2s ease;
        }

        .nav-logo:hover {
            opacity: 0.8;
        }

        /* Bottom status bar styling */
        .status-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: rgba(128, 128, 128, 0.10);
            backdrop-filter: blur(10px);
            border-top: 1px solid rgba(128, 128, 128, 0.25);
            padding: 0.5rem 1rem;
            z-index: 1000;
            font-size: 0.85rem;
            color: inherit;
            opacity: 0.85;
        }

        .status-indicator {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }

        .status-light {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            display: inline-block;
        }

        .status-light.active {
            background-color: #00c851;
            box-shadow: 0 0 4px rgba(0, 200, 81, 0.4);
        }

        .status-light.inactive {
            background-color: #ff4444;
            box-shadow: 0 0 4px rgba(255, 68, 68, 0.4);
        }

        .status-light.unknown {
            background-color: #ffbb33;
            box-shadow: 0 0 4px rgba(255, 187, 51, 0.4);
        }

        /* FIXED: Main content padding and spacing */
        .main-content {
            padding-bottom: 3rem;
            padding-top: 0 !important;
            margin-top: 0 !important;
        }

        /* FIXED: Reduce spacing after success messages */
        div.stAlert {
            margin-bottom: 0.5rem !important;
            margin-top: 0 !important;
        }

        /* FIXED: Success message specific spacing */
        .stSuccess {
            padding: 0.75rem 1rem !important;
            margin: 0 0 1rem 0 !important;
            border-radius: 8px;
            border-left: 4px solid #00c851;
        }

        /* FIXED: Container spacing */
        .main .block-container {
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
            max-width: 100%;
        }

        /* FIXED: Reduce vertical gaps between elements */
        div[data-testid="stVerticalBlock"] > [style*="gap"] {
            gap: 0.5rem !important;
        }

        /* FIXED: Reduce spacing in main content area */
        .element-container {
            margin-bottom: 0.5rem !important;
        }

        /* FIXED: Specific fix for container spacing */
        div[data-testid="stVerticalBlock"] {
            gap: 0.5rem !important;
        }

        /* Workspace card styling - clean design */
        .workspace-card {
            background: white;
            border: 2px solid #e1e5e9;
            color: #333 !important;
            padding: 1.5rem;
            border-radius: 12px;
            margin-bottom: 1.5rem;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            transition: all 0.3s ease;
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }

        .workspace-card:hover {
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            transform: translateY(-2px);
            border-color: #1f77b4;
        }

        .workspace-card-content {
            backdrop-filter: blur(2px);
            padding: 1rem;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.95);
        }

        .workspace-card h3 {
            margin: 0;
            color: #1f77b4 !important;
            font-size: 1.4rem;
            font-weight: 600;
        }

        .workspace-card p {
            color: #666 !important;
            margin: 0.5rem 0 0 0;
            font-size: 0.95rem;
            line-height: 1.4;
        }

        /* Workspace header in main application */
        .workspace-header {
            background: linear-gradient(90deg, #1f77b4, #ff7f0e);
            color: white;
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            text-align: center;
        }

        .workspace-header h2 {
            margin: 0;
            color: white !important;
        }

        .workspace-header p {
            margin: 0;
            opacity: 0.9;
        }

        /* Improved radio button styling for module selection */
        div[data-testid="stRadio"] > div {
            gap: 0.5rem;
        }
        
        div[data-testid="stRadio"] > div > label {
            padding: 0.5rem 1rem;
            border-radius: 6px;
            transition: all 0.2s ease;
            cursor: pointer;
            border: 1px solid transparent;
        }
        
        div[data-testid="stRadio"] > div > label:hover {
            background-color: rgba(31, 119, 180, 0.1);
            border-color: rgba(31, 119, 180, 0.3);
        }
        
        div[data-testid="stRadio"] > div > label[data-checked="true"] {
            background-color: rgba(31, 119, 180, 0.2);
            border-color: rgba(31, 119, 180, 0.5);
        }

        /* Loading indicator improvements */
        .stSpinner {
            text-align: center;
            padding: 2rem;
        }

        /* Button styling improvements */
        .stButton > button {
            transition: all 0.2s ease;
        }

        .stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }

        /* Metric styling improvements */
        div[data-testid="metric-container"] {
            background: rgba(128, 128, 128, 0.06);
            padding: 1rem;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            border: 1px solid rgba(128, 128, 128, 0.25);
        }

        /* Expander styling improvements */
        .streamlit-expanderHeader {
            background-color: rgba(31, 119, 180, 0.05);
            border-radius: 6px;
            margin-top: 0.25rem !important;
            margin-bottom: 0.25rem !important;
        }

        /* Error message styling */
        .stError {
            padding: 1rem;
            border-radius: 8px;
            border-left: 4px solid #ff4444;
            margin: 0 0 1rem 0 !important;
        }

        .stWarning {
            padding: 1rem;  
            border-radius: 8px;
            border-left: 4px solid #ffbb33;
            margin: 0 0 1rem 0 !important;
        }

        .stInfo {
            padding: 1rem;
            border-radius: 8px;
            border-left: 4px solid #33b5e5;
            margin: 0 0 1rem 0 !important;
        }

        /* FIXED: Reduce header spacing */
        .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
            margin-top: 0.5rem !important;
            margin-bottom: 0.5rem !important;
        }

        /* FIXED: Button spacing */
        .row-widget.stButton {
            margin-top: 0 !important;
            margin-bottom: 0.25rem !important;
        }

        /* FIXED: Overall spacing reduction */
        [data-testid="stHorizontalBlock"] {
            gap: 0.5rem !important;
        }

        /* FIXED: Remove excessive padding from elements */
        .element-container > div {
            margin-bottom: 0 !important;
        }

        /* FIXED: Streamlit container adjustments */
        section[data-testid="stSidebar"] > div {
            padding-top: 2rem;
        }

        /* FIXED: Main container tighter spacing */
        .main > div {
            padding-top: 1rem !important;
        }
    </style>
    """


def get_dark_overrides() -> str:
    """Dark-theme overrides, injected on top of the base styles when the user
    picks Dark in the sidebar. Streamlit 1.59 no longer exposes a theme toggle in
    its menu and can't switch the base theme at runtime from Python, so we
    re-colour the main surfaces ourselves. Workspace cards stay light 'image
    tiles' (their text keeps its own colour via !important) and remain readable."""
    # NOTE: selectors are prefixed with `html body` to raise specificity above
    # Streamlit's pinned light-theme text colour (config.toml textColor), which
    # otherwise wins and leaves dark text on the dark background.
    return """
    <style>
        /* ---- Dark appearance (toggled from the sidebar) ---- */
        /* Backgrounds */
        html body .stApp, html body [data-testid="stAppViewContainer"],
        html body [data-testid="stHeader"], html body [data-testid="stMain"],
        html body .main, html body .block-container {
            background-color: #0e1117 !important;
        }
        html body [data-testid="stSidebar"],
        html body section[data-testid="stSidebar"] > div {
            background-color: #1a1d24 !important;
        }
        /* Text — broad + high specificity so it beats the pinned light text */
        html body .stApp, html body .stApp p, html body .stApp span,
        html body .stApp li, html body .stApp label, html body .stApp small,
        html body .stApp strong, html body .stApp em, html body .stApp td,
        html body .stApp th, html body .stApp a,
        html body .stApp h1, html body .stApp h2, html body .stApp h3,
        html body .stApp h4, html body .stApp h5, html body .stApp h6,
        html body [data-testid="stMarkdownContainer"],
        html body [data-testid="stMarkdownContainer"] *,
        html body [data-testid="stWidgetLabel"],
        html body [data-testid="stWidgetLabel"] *,
        html body [data-testid="stMetricValue"],
        html body [data-testid="stMetricLabel"],
        html body [data-testid="stSidebar"] * {
            color: #e6e6e6 !important;
        }
        /* Inputs / selects / textareas (BaseWeb) */
        html body input, html body textarea,
        html body [data-baseweb="input"], html body [data-baseweb="base-input"],
        html body [data-baseweb="textarea"], html body [data-baseweb="select"] > div {
            background-color: #262730 !important;
            color: #e6e6e6 !important;
            border-color: rgba(230, 230, 230, 0.25) !important;
        }
        /* Dropdown / popover menus */
        html body [data-baseweb="popover"] [role="listbox"],
        html body [data-baseweb="menu"], html body ul[role="listbox"],
        html body li[role="option"] {
            background-color: #262730 !important; color: #e6e6e6 !important;
        }
        /* Buttons */
        html body .stButton > button, html body .stDownloadButton > button,
        html body .stFormSubmitButton > button {
            background-color: #262730 !important;
            color: #e6e6e6 !important;
            border: 1px solid rgba(230, 230, 230, 0.25) !important;
        }
        html body .stButton > button:hover { border-color: #1f77b4 !important; }
        /* Code / preformatted */
        html body code, html body pre {
            background-color: #1a1d24 !important; color: #e6e6e6 !important;
        }
        html body [data-baseweb="tab"] { color: #e6e6e6 !important; }
        /* Workspace cards -> dark tiles (uniform with the rest) */
        html body .workspace-card {
            background-color: #1a1d24 !important;
            border-color: rgba(230, 230, 230, 0.2) !important;
        }
        html body .workspace-card-content { background: rgba(0, 0, 0, 0.5) !important; }
        html body .workspace-card, html body .workspace-card p { color: #d0d0d0 !important; }
        html body .workspace-card h3 { color: #58a6e0 !important; }
        /* Transparent logos need a white backing so they stay visible on dark:
           the main landing logo, the sidebar nav logo, and the ERA-Net funding
           logo (the other image in the sidebar/context bar). */
        html body .logo-container img,
        html body .nav-logo,
        html body img[alt*="ERA-Net"] {
            background-color: #ffffff !important;
            padding: 12px !important;
            border-radius: 12px !important;
        }
    </style>
    """


# Additional utility functions for styling
def apply_platform_styles():
    """Apply the base platform styles, plus dark overrides when the user has
    picked Dark in the sidebar (st.session_state['app_theme'])."""
    import streamlit as st
    st.markdown(get_platform_styles(), unsafe_allow_html=True)
    if st.session_state.get("app_theme", "Light") == "Dark":
        st.markdown(get_dark_overrides(), unsafe_allow_html=True)


def render_appearance_toggle():
    """Render the Light/Dark appearance selector in the sidebar. Cheap; call once
    per run right after apply_platform_styles(). Changing it reruns the app, and
    apply_platform_styles() (at the top) then injects the matching stylesheet."""
    import streamlit as st
    st.sidebar.radio(
        "Appearance",
        options=["Light", "Dark"],
        horizontal=True,
        key="app_theme",
        help="Light is the default. Dark improves viewing on macOS / dark-mode displays.",
    )


def get_custom_css_classes() -> dict:
    """
    Get dictionary of custom CSS class names for use in components

    Returns:
        dict: Dictionary of CSS class names
    """
    return {
        'user_greeting': 'user-greeting',
        'workspace_card': 'workspace-card',
        'workspace_card_content': 'workspace-card-content',
        'workspace_header': 'workspace-header',
        'main_header': 'main-header',
        'logo_container': 'logo-container',
        'module_content': 'module-content',
        'loading_hidden': 'loading-hidden'
    }