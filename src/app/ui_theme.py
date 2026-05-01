"""
Warm light theme for the main Streamlit investigation page.

- Investigation-specific rules are scoped to ``section[data-testid="stMain"]`` so the
  multipage **sidebar** does not pick up bordered “card” chrome meant for the main column.
- **Full Interactive Graph** calls ``inject_secondary_page_layout_reset()`` to undo the
  editorial max-width if the user previously loaded the home page in the same browser tab.
- Shared **sidebar chrome** (flatter nav, less empty-looking surfaces) is injected from
  both pages via ``inject_sidebar_chrome_styles()``.
"""

from __future__ import annotations

from html import escape

import streamlit as st

_MAIN_MAX_WIDTH_PX = 900

# Tonal scale — stronger separation, still warm cream / graphite / sage (no bright accents)
_PAGE_BG = "#ebe6db"
_SURFACE = "#ffffff"
_SURFACE_BORDER = "#a89e8c"
_TEXT = "#1f1f22"
_TEXT_SECONDARY = "#45423c"
_MUTED_LINE = "#948c7e"
_INPUT_BORDER = "#8a8174"
_INPUT_BG = "#faf9f7"
_PRIMARY = "#4d584c"
_PRIMARY_HOVER = "#3d463c"
_PRIMARY_BORDER = "#2f352e"
_FOCUS_RING = "rgba(77, 88, 76, 0.45)"

# Editorial serif for titles/major headings only; system UI sans elsewhere (Streamlit has no webfont loader).
_SERIF_HEADING = (
    '"Palatino Linotype", Palatino, "Book Antiqua", "Iowan Old Style", '
    'Georgia, "Noto Serif", "Times New Roman", serif'
)
_SANS_UI = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", '
    "Arial, sans-serif"
)


def inject_sidebar_chrome_styles() -> None:
    """Flatter sidebar: less ‘empty card’ noise from default secondary surfaces on nav."""
    st.markdown(
        f"""
<style>
  section[data-testid="stSidebar"] {{
    background-color: #e4dfd4 !important;
    border-right: 1px solid #9a9284 !important;
  }}
  /* Multipage nav: text links, not heavy pills */
  section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"] {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: {_TEXT} !important;
    font-size: 0.95rem !important;
    font-weight: 500 !important;
    border-radius: 8px !important;
    padding: 0.4rem 0.55rem !important;
  }}
  section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"]:hover {{
    background: rgba(0, 0, 0, 0.045) !important;
  }}
  section[data-testid="stSidebar"] [data-testid="stSidebarNavLink"][aria-current="page"] {{
    background: rgba(85, 96, 84, 0.12) !important;
    color: {_TEXT} !important;
  }}
  /* Sidebar widgets: clearer single surface, not stacked ghost boxes */
  section[data-testid="stSidebar"] .block-container {{
    font-size: 1.02rem !important;
    padding-top: 0.75rem !important;
    padding-bottom: 1rem !important;
  }}
  section[data-testid="stSidebar"] [data-baseweb="select"] > div,
  section[data-testid="stSidebar"] [data-baseweb="input"] {{
    border-radius: 10px !important;
    border-color: {_INPUT_BORDER} !important;
    background-color: {_SURFACE} !important;
  }}
  section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    color: {_TEXT_SECONDARY} !important;
  }}
</style>
""",
        unsafe_allow_html=True,
    )


def inject_secondary_page_layout_reset() -> None:
    """Undo home-page editorial width / main-column overrides (e.g. full graph page)."""
    st.markdown(
        """
<style>
  section[data-testid="stMain"] > div {
    max-width: none !important;
    margin-left: 0 !important;
    margin-right: 0 !important;
  }
  section[data-testid="stMain"] .block-container {
    max-width: none !important;
  }
</style>
""",
        unsafe_allow_html=True,
    )


def inject_main_investigation_styles() -> None:
    """Theme for the investigation home: main column only + global app background."""
    st.markdown(
        f"""
<style>
  .stApp,
  [data-testid="stAppViewContainer"] {{
    background-color: {_PAGE_BG} !important;
  }}
  section[data-testid="stMain"] {{
    background-color: {_PAGE_BG};
  }}
  div[data-testid="stToolbar"] {{
    background-color: transparent;
  }}

  /* Editorial width — main column only */
  section[data-testid="stMain"] > div {{
    max-width: {_MAIN_MAX_WIDTH_PX}px;
    margin-left: auto;
    margin-right: auto;
  }}

  section[data-testid="stMain"] .block-container {{
    color: {_TEXT};
    font-family: {_SANS_UI} !important;
    font-size: 1.06rem !important;
    line-height: 1.58 !important;
    padding-top: 1.35rem;
    padding-bottom: 2.75rem;
  }}

  section[data-testid="stMain"] h1 {{
    font-family: {_SERIF_HEADING} !important;
    font-weight: 600 !important;
    letter-spacing: -0.025em !important;
    color: #18181a !important;
    font-size: 2.125rem !important;
    margin-bottom: 0.4rem !important;
  }}
  section[data-testid="stMain"] h2,
  section[data-testid="stMain"] h3 {{
    font-family: {_SERIF_HEADING} !important;
    font-weight: 600 !important;
    color: #1c1c1f !important;
  }}
  section[data-testid="stMain"] h2 {{
    font-size: 1.35rem !important;
    margin-top: 1.5rem !important;
    margin-bottom: 0.5rem !important;
  }}
  section[data-testid="stMain"] h3 {{
    font-size: 1.22rem !important;
    margin-top: 1.45rem !important;
    margin-bottom: 0.55rem !important;
  }}

  section[data-testid="stMain"] p.inv-section-label {{
    font-family: {_SANS_UI} !important;
    font-size: 0.8rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    color: {_TEXT_SECONDARY} !important;
    margin: 0 0 0.45rem 0 !important;
  }}

  section[data-testid="stMain"] [data-testid="stMetricValue"] {{
    font-size: 1.38rem !important;
    font-weight: 600 !important;
    color: #232326 !important;
  }}
  section[data-testid="stMain"] [data-testid="stMetricLabel"] {{
    font-size: 0.74rem !important;
    font-weight: 600 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
    color: {_TEXT_SECONDARY} !important;
  }}
  section[data-testid="stMain"] [data-testid="metric-container"] {{
    background-color: {_SURFACE} !important;
    border: 1px solid {_SURFACE_BORDER} !important;
    border-radius: 14px !important;
    padding: 0.75rem 0.95rem !important;
    box-shadow: 0 2px 6px rgba(24, 24, 27, 0.07) !important;
  }}

  section[data-testid="stMain"] .stButton > button[kind="primary"],
  section[data-testid="stMain"] div[data-testid="stFormSubmitButton"] button[kind="primary"] {{
    font-family: {_SANS_UI} !important;
    background-color: {_PRIMARY} !important;
    color: #faf9f6 !important;
    border: 1px solid {_PRIMARY_BORDER} !important;
    border-radius: 11px !important;
    font-weight: 600 !important;
    font-size: 1.04rem !important;
    padding: 0.54rem 1.2rem !important;
    box-shadow: 0 2px 5px rgba(24, 24, 27, 0.16) !important;
  }}
  section[data-testid="stMain"] .stButton > button[kind="primary"]:hover,
  section[data-testid="stMain"] div[data-testid="stFormSubmitButton"] button[kind="primary"]:hover {{
    background-color: {_PRIMARY_HOVER} !important;
    border-color: #252b24 !important;
    color: #ffffff !important;
  }}
  section[data-testid="stMain"] .stButton > button[kind="primary"]:focus-visible,
  section[data-testid="stMain"] div[data-testid="stFormSubmitButton"] button[kind="primary"]:focus-visible {{
    outline: 2px solid #7d8a7b !important;
    outline-offset: 2px !important;
  }}

  section[data-testid="stMain"] .stButton > button[kind="secondary"],
  section[data-testid="stMain"] div[data-testid="stFormSubmitButton"] button[kind="secondary"] {{
    font-family: {_SANS_UI} !important;
    border-radius: 11px !important;
    border: 1px solid {_SURFACE_BORDER} !important;
    color: {_TEXT} !important;
    background-color: {_INPUT_BG} !important;
    font-size: 1.04rem !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 3px rgba(24, 24, 27, 0.1) !important;
  }}
  section[data-testid="stMain"] .stButton > button[kind="secondary"]:hover {{
    border-color: #8a8174 !important;
    background-color: {_SURFACE} !important;
  }}

  section[data-testid="stMain"] div[data-testid="stDownloadButton"] button {{
    font-family: {_SANS_UI} !important;
    border-radius: 11px !important;
    border: 1px solid {_SURFACE_BORDER} !important;
    color: {_TEXT} !important;
    background-color: {_INPUT_BG} !important;
    font-weight: 600 !important;
    font-size: 1.04rem !important;
    box-shadow: 0 1px 3px rgba(24, 24, 27, 0.1) !important;
  }}
  section[data-testid="stMain"] div[data-testid="stDownloadButton"] button:hover {{
    border-color: #8a8174 !important;
    background-color: {_SURFACE} !important;
  }}

  /* Bordered layout containers (composer, results) — main column only */
  section[data-testid="stMain"] div[data-testid="stVerticalBlockBorderWrapper"] {{
    background-color: {_SURFACE} !important;
    border: 1px solid {_SURFACE_BORDER} !important;
    border-radius: 16px !important;
    padding: 1.15rem 1.25rem 1.25rem 1.25rem !important;
    margin-bottom: 1.35rem !important;
    box-shadow: 0 2px 10px rgba(24, 24, 27, 0.08) !important;
  }}

  section[data-testid="stMain"] hr {{
    margin: 1.85rem 0 !important;
    border: none !important;
    border-top: 1px solid {_MUTED_LINE} !important;
  }}

  section[data-testid="stMain"] .stTextArea textarea {{
    font-family: {_SANS_UI} !important;
    border-radius: 12px !important;
    border: 1px solid {_INPUT_BORDER} !important;
    background-color: {_INPUT_BG} !important;
    color: {_TEXT} !important;
    font-size: 1.06rem !important;
    line-height: 1.5 !important;
    box-shadow: inset 0 1px 2px rgba(24, 24, 27, 0.04) !important;
  }}
  section[data-testid="stMain"] .stTextArea textarea:focus {{
    border-color: #7d8a7b !important;
    box-shadow: 0 0 0 2px {_FOCUS_RING} !important;
  }}

  section[data-testid="stMain"] [data-baseweb="select"] > div {{
    font-family: {_SANS_UI} !important;
    border-radius: 11px !important;
    border: 1px solid {_INPUT_BORDER} !important;
    background-color: {_INPUT_BG} !important;
    min-height: 42px !important;
    box-shadow: inset 0 1px 2px rgba(24, 24, 27, 0.04) !important;
  }}
  section[data-testid="stMain"] [data-baseweb="select"]:focus-within > div {{
    border-color: #7d8a7b !important;
    box-shadow: 0 0 0 2px {_FOCUS_RING} !important;
  }}

  section[data-testid="stMain"] div[data-testid="stAlert"] {{
    border-radius: 12px !important;
    border: 1px solid {_SURFACE_BORDER} !important;
    font-size: 1.04rem !important;
    font-family: {_SANS_UI} !important;
  }}

  section[data-testid="stMain"] .streamlit-expander {{
    border: 1px solid {_SURFACE_BORDER} !important;
    border-radius: 12px !important;
    background-color: #f7f5f1 !important;
    margin-bottom: 0.5rem !important;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(24, 24, 27, 0.06) !important;
  }}
  section[data-testid="stMain"] .streamlit-expanderHeader {{
    font-family: {_SANS_UI} !important;
    font-weight: 600 !important;
    font-size: 1.04rem !important;
    color: {_TEXT} !important;
  }}

  section[data-testid="stMain"] .stCaption,
  section[data-testid="stMain"] small[data-testid="stCaption"] {{
    font-family: {_SANS_UI} !important;
    color: {_TEXT_SECONDARY} !important;
    font-size: 0.97rem !important;
  }}

  section[data-testid="stMain"] [data-testid="stWidgetLabel"] {{
    font-family: {_SANS_UI} !important;
    font-size: 0.94rem !important;
    font-weight: 600 !important;
    color: {_TEXT_SECONDARY} !important;
  }}

  section[data-testid="stMain"] .stCodeBlock {{
    border-radius: 11px !important;
    border: 1px solid {_SURFACE_BORDER} !important;
  }}

  section[data-testid="stMain"] [data-testid="stSlider"] {{
    padding-top: 0.25rem !important;
    padding-bottom: 0.5rem !important;
  }}
</style>
""",
        unsafe_allow_html=True,
    )


def inject_main_page_theme() -> None:
    """Full chrome for the investigation home page (sidebar + main column)."""
    inject_sidebar_chrome_styles()
    inject_main_investigation_styles()


def section_label(text: str) -> None:
    st.markdown(
        f'<p class="inv-section-label">{escape(text)}</p>',
        unsafe_allow_html=True,
    )
