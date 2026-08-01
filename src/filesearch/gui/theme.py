"""Design tokens and the generated stylesheet.

Every colour, radius and spacing value in the GUI comes from here. Nothing
else in the codebase should contain a hex literal.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette

LIGHT = "light"
DARK = "dark"


@dataclass(frozen=True)
class Palette:
    """Surface, text and accent colours for one theme."""

    # Surfaces, from the page backdrop up to raised cards.
    canvas: str
    surface: str
    surface_sunk: str
    surface_raised: str
    surface_hover: str
    rail: str

    # Hairlines. `border` separates, `border_strong` outlines an interactive edge.
    border: str
    border_strong: str

    # Text, three steps of emphasis.
    text: str
    text_muted: str
    text_faint: str

    # The single accent. Used for focus, the active nav item and relevance only.
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    accent_wash: str

    danger: str
    danger_wash: str
    shadow: str

    # Focus ring. Drawn as a second, softer stroke outside the accent border so
    # the focused edge reads at a glance without thickening the control.
    focus_ring: str

    # Elevation. Drop shadows are layered from these; light and dark need
    # different opacities because a dark surface swallows a soft shadow.
    shadow_soft: str
    shadow_key: str


# Neutral greys throughout: hierarchy comes from scale and space, not hue.
# Teal is the identity but earns its place in three roles only.
PALETTES: dict[str, Palette] = {
    LIGHT: Palette(
        canvas="#f6f6f7",
        surface="#ffffff",
        surface_sunk="#f1f1f3",
        surface_raised="#ffffff",
        surface_hover="#ebebee",
        rail="#fbfbfc",
        border="#e4e4e7",
        border_strong="#d1d1d6",
        text="#18181b",
        text_muted="#52525b",
        text_faint="#686872",
        accent="#0f7d6b",
        accent_hover="#0c6959",
        accent_pressed="#0a5548",
        accent_text="#ffffff",
        accent_wash="#e8f3f0",
        danger="#b4232a",
        danger_wash="#fdecec",
        shadow="#000000",
        focus_ring="rgba(15, 125, 107, 0.22)",
        shadow_soft="#0D18181B",
        shadow_key="#1718181B",
    ),
    DARK: Palette(
        canvas="#0e0e10",
        surface="#141416",
        surface_sunk="#0a0a0c",
        surface_raised="#1c1c1f",
        surface_hover="#26262b",
        rail="#111113",
        border="#2a2a2e",
        border_strong="#3a3a40",
        text="#f4f4f5",
        text_muted="#a1a1aa",
        text_faint="#8e8e98",
        accent="#2dd4a7",
        accent_hover="#4ee0b8",
        accent_pressed="#22b48d",
        accent_text="#06231c",
        accent_wash="#16302a",
        danger="#f87171",
        danger_wash="#33191b",
        shadow="#000000",
        focus_ring="rgba(45, 212, 167, 0.26)",
        shadow_soft="#52000000",
        shadow_key="#75000000",
    ),
}


# Spacing scale. Applied unevenly on purpose: tight within a group, generous
# between groups, so the layout shows what belongs to what.
SPACE = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "2xl": 32, "3xl": 48}

# Radius scale, sized so nesting works out: `outer = inner + padding`.
# A control with 6px radius inside a 16px-padded card wants a 22px card — hence
# `xl`. Mismatched radii on nested surfaces is the single most common thing that
# makes an interface feel slightly wrong without anyone being able to say why.
RADIUS = {"xs": 3, "sm": 5, "md": 7, "lg": 11, "xl": 14, "pill": 999}

# Elevation. Each step is (blur, y-offset) for a layered drop shadow: a tight
# key shadow that grounds the element plus a wide soft one for ambient depth.
# Borders are kept as a hairline on top, never as the only separation.
ELEVATION = {
    "raised": (10, 1),
    "overlay": (24, 4),
    "popover": (36, 8),
}

# Type scale with real contrast between steps, not a 14-18px mush.
TYPE = {"display": 25, "title": 18, "body": 14, "small": 13, "micro": 11}

# Letter-spacing, in px, applied where the size warrants it: large text needs
# tightening, all-caps micro labels need opening up.
TRACKING = {"display": -0.4, "title": -0.2, "caps": 0.6}

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", sans-serif'


def palette(name: str) -> Palette:
    return PALETTES.get(name, PALETTES[LIGHT])


def base_font() -> QFont:
    """The application font, with tabular figures.

    Lining tabular numerals keep scores and counters from reflowing as digits
    change during a count-up. `PreferAntialias` plus subpixel positioning gives
    the closest thing Qt has to proper font smoothing on Windows.
    """
    font = QFont("Segoe UI Variable Text")
    if not font.exactMatch():
        font = QFont("Segoe UI")
    font.setPixelSize(TYPE["body"])
    font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
    font.setHintingPreference(QFont.PreferVerticalHinting)
    for tag in ("tnum", "lnum", "kern", "liga"):
        try:
            font.setFeature(QFont.Tag(tag), 1)
        except (AttributeError, TypeError, ValueError):
            # setFeature landed in Qt 6.7; older builds keep the defaults.
            break
    return font


def qt_palette(name: str) -> QPalette:
    """A QPalette matching the theme.

    QSS does not reach every native surface. Message boxes, tooltips and text
    selection read from the palette, so both have to be set for dark mode to
    look right.
    """
    c = palette(name)
    p = QPalette()
    p.setColor(QPalette.Window, QColor(c.canvas))
    p.setColor(QPalette.WindowText, QColor(c.text))
    p.setColor(QPalette.Base, QColor(c.surface))
    p.setColor(QPalette.AlternateBase, QColor(c.surface_sunk))
    p.setColor(QPalette.Text, QColor(c.text))
    p.setColor(QPalette.PlaceholderText, QColor(c.text_faint))
    p.setColor(QPalette.Button, QColor(c.surface))
    p.setColor(QPalette.ButtonText, QColor(c.text))
    p.setColor(QPalette.Highlight, QColor(c.accent))
    p.setColor(QPalette.HighlightedText, QColor(c.accent_text))
    p.setColor(QPalette.ToolTipBase, QColor(c.surface_raised))
    p.setColor(QPalette.ToolTipText, QColor(c.text))
    p.setColor(QPalette.Link, QColor(c.accent))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(c.text_faint))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c.text_faint))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(c.text_faint))
    return p


def stylesheet(name: str) -> str:
    """Build the full QSS for a theme.

    Radius and border are always declared on the same element so the stroke
    follows the arc instead of dying at the corners.
    """
    c = palette(name)
    s, r, t, tr = SPACE, RADIUS, TYPE, TRACKING

    return f"""
* {{
    font-family: {FONT_STACK};
}}

QWidget {{
    background: transparent;
    color: {c.text};
    font-size: {t["body"]}px;
}}

QMainWindow, #shell {{
    background: {c.canvas};
}}

QToolTip {{
    background: {c.surface_raised};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {r["md"]}px;
    padding: {s["xs"]}px {s["sm"]}px;
    font-size: {t["small"]}px;
}}

/* ---------------------------------------------------------------- nav rail */

#navRail {{
    background: {c.rail};
    border-right: 1px solid {c.border};
}}

#navBrand {{
    color: {c.text};
    font-size: {t["body"]}px;
    font-weight: 600;
}}

/* Nav items are pills inset from the rail edge rather than full-bleed rows with
   a left marker. The inset gives the active item a shape of its own, and the
   radius is concentric with the rail's own 8px inset. */
#navItem {{
    background: transparent;
    border: 0;
    border-radius: {r["md"]}px;
    color: {c.text_muted};
    font-size: {t["body"]}px;
    font-weight: 500;
    padding: {s["sm"]}px {s["md"]}px;
    text-align: left;
}}

#navItem:hover {{
    background: {c.surface_hover};
    color: {c.text};
}}

#navItem:checked {{
    background: {c.accent_wash};
    color: {c.text};
    font-weight: 600;
}}

#navItem:focus {{
    background: {c.surface_hover};
    border: 1px solid {c.focus_ring};
}}

#navFooterLabel {{
    color: {c.text_faint};
    font-size: {t["micro"]}px;
}}

/* The one all-caps label in the app: small enough to need opened tracking. */
#navFooterCaption {{
    color: {c.text_faint};
    font-size: {t["micro"]}px;
    font-weight: 600;
    letter-spacing: {tr["caps"]}px;
}}

#navDivider {{
    background: {c.border};
    border: 0;
    max-height: 1px;
    min-height: 1px;
}}

/* ------------------------------------------------------------------- pages */

/* Display and title sizes get negative tracking: at 25px the default spacing
   between glyphs reads loose, which makes a heading look unresolved. */
#pageTitle {{
    color: {c.text};
    font-size: {t["display"]}px;
    font-weight: 650;
    letter-spacing: {tr["display"]}px;
}}

#pageLead {{
    color: {c.text_muted};
    font-size: {t["body"]}px;
}}

#sectionTitle {{
    color: {c.text};
    font-size: {t["title"]}px;
    font-weight: 600;
    letter-spacing: {tr["title"]}px;
}}

#fieldLabel {{
    color: {c.text_muted};
    font-size: {t["small"]}px;
}}

#muted {{
    color: {c.text_muted};
    font-size: {t["small"]}px;
}}

#faint {{
    color: {c.text_faint};
    font-size: {t["micro"]}px;
}}

#danger {{
    color: {c.danger};
    font-size: {t["small"]}px;
}}

/* The card is 16px-padded and holds 7px-radius buttons, so its own radius is
   14px: inner + padding, near enough that the arcs stay concentric. Depth comes
   from a drop shadow (see elevation.py); the hairline only defines the edge. */
#card {{
    background: {c.surface_raised};
    border: 1px solid {c.border};
    border-radius: {r["xl"]}px;
}}

#card:hover {{
    border: 1px solid {c.border_strong};
}}

#panel {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: {r["xl"]}px;
}}

#divider {{
    background: {c.border};
    border: 0;
    max-height: 1px;
    min-height: 1px;
}}

/* --------------------------------------------------------------- text bits */

/* The relevance figure changes per result, so it must not reflow the row: the
   base font carries tabular figures and the label is fixed-width. */
#score {{
    color: {c.accent};
    font-size: {t["title"]}px;
    font-weight: 650;
    letter-spacing: {tr["title"]}px;
}}

/* A pill behind the score reads as a badge rather than loose text, and gives
   the strongest colour in the card a container to sit in. */
#scoreBadge {{
    background: {c.accent_wash};
    border: 0;
    border-radius: {r["sm"]}px;
}}

#resultName {{
    color: {c.text};
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.1px;
}}

#resultMeta {{
    color: {c.text_faint};
    font-size: {t["micro"]}px;
    font-weight: 600;
    letter-spacing: {tr["caps"]}px;
}}

#resultSnippet {{
    color: {c.text_muted};
    font-size: {t["small"]}px;
}}

#resultPath {{
    color: {c.text_faint};
    font-size: {t["micro"]}px;
}}

/* ------------------------------------------------------------------ inputs */

QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {c.surface};
    border: 1px solid {c.border_strong};
    border-radius: {r["md"]}px;
    color: {c.text};
    padding: {s["sm"]}px {s["md"]}px;
    selection-background-color: {c.accent};
    selection-color: {c.accent_text};
}}

QLineEdit:hover, QSpinBox:hover {{
    border: 1px solid {c.text_faint};
}}

/* Focus is an accent edge plus a soft outline ring. QSS has no box-shadow, so
   `outline` stands in: it sits outside the border and does not shift layout,
   which a thicker border would. */
QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {c.accent};
    outline: 2px solid {c.focus_ring};
    outline-offset: 0px;
}}

QLineEdit:disabled, QSpinBox:disabled {{
    background: {c.surface_sunk};
    color: {c.text_faint};
}}

QLineEdit[readOnly="true"] {{
    background: {c.surface_sunk};
    color: {c.text_muted};
}}

/* The search field is the primary target on the page and is sized like it:
   larger radius to match its height, and generous horizontal padding so the
   caret is not crowded against the edge. */
#heroInput {{
    font-size: {t["title"]}px;
    letter-spacing: {tr["title"]}px;
    padding: {s["md"]}px {s["lg"]}px;
    border-radius: {r["lg"]}px;
    min-height: 22px;
}}

QWidget#searchFilters {{
    background: transparent;
    border: 0;
}}

/* The stepper is one segmented control, not three loose buttons: a sunk track
   holds them, so −, the value and + read as parts of the same object. */
QWidget#stepper {{
    background: {c.surface_sunk};
    border: 1px solid {c.border};
    border-radius: {r["lg"]}px;
}}

QWidget#searchFilters QLabel#filterValue {{
    color: {c.text};
    font-weight: 600;
}}

/* Inner radius = outer 11 − 4px track padding. */
QWidget#stepper QPushButton#quiet {{
    background: transparent;
    border: 0;
    border-radius: {r["md"]}px;
    padding: 0;
}}

QWidget#stepper QPushButton#quiet:hover {{
    background: {c.surface_hover};
}}

QWidget#stepper QPushButton#quiet:pressed {{
    background: {c.border};
}}

QWidget#stepper QPushButton#quiet:disabled {{
    background: transparent;
}}

QPushButton#filterMenu {{
    background: {c.surface};
    border: 1px solid {c.border_strong};
    border-radius: {r["md"]}px;
    color: {c.text};
    padding: 0 {s["md"]}px;
    text-align: left;
}}

QPushButton#filterMenu:hover {{
    border-color: {c.text_faint};
    background: {c.surface_hover};
}}

QPushButton#filterMenu:focus {{
    border-color: {c.accent};
    outline: 2px solid {c.focus_ring};
}}

QMenu {{
    background: {c.surface_raised};
    color: {c.text};
    border: 1px solid {c.border};
    border-radius: {r["lg"]}px;
    padding: {s["xs"]}px;
}}

/* Inner radius = outer 11 − 4px menu padding. */
QMenu::item {{
    border-radius: {r["md"]}px;
    padding: {s["sm"]}px {s["2xl"]}px {s["sm"]}px {s["md"]}px;
}}

QMenu::item:selected {{
    background: {c.accent_wash};
    color: {c.text};
}}

QMenu::separator {{
    background: {c.border};
    height: 1px;
    margin: {s["xs"]}px {s["sm"]}px;
}}

QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent;
    border: 0;
    width: 16px;
}}

QSpinBox::up-arrow, QSpinBox::down-arrow {{
    width: 7px;
    height: 7px;
}}

QSpinBox::up-arrow {{
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-bottom: 4px solid {c.text_faint};
}}

QSpinBox::down-arrow {{
    image: none;
    border-left: 3px solid transparent;
    border-right: 3px solid transparent;
    border-top: 4px solid {c.text_faint};
}}

/* ----------------------------------------------------------------- buttons */

/* 34px minimum height keeps every button inside a comfortable hit area even
   when its label is short. Icon-only controls extend theirs in code. */
QPushButton {{
    background: {c.surface};
    border: 1px solid {c.border_strong};
    border-radius: {r["md"]}px;
    color: {c.text};
    font-size: {t["body"]}px;
    font-weight: 500;
    padding: {s["sm"]}px {s["md"]}px;
    min-height: 18px;
}}

QPushButton:hover {{
    background: {c.surface_hover};
    border: 1px solid {c.text_faint};
}}

QPushButton:pressed {{
    background: {c.surface_sunk};
    border: 1px solid {c.border_strong};
}}

QPushButton:focus {{
    border: 1px solid {c.accent};
    outline: 2px solid {c.focus_ring};
}}

QPushButton:disabled {{
    background: {c.surface_sunk};
    border: 1px solid {c.border};
    color: {c.text_faint};
}}

QPushButton#primary {{
    background: {c.accent};
    border: 1px solid {c.accent};
    color: {c.accent_text};
    font-weight: 600;
}}

QPushButton#primary:hover {{
    background: {c.accent_hover};
    border: 1px solid {c.accent_hover};
}}

QPushButton#primary:pressed {{
    background: {c.accent_pressed};
    border: 1px solid {c.accent_pressed};
}}

QPushButton#primary:focus {{
    border: 1px solid {c.accent};
    outline: 2px solid {c.focus_ring};
}}

QPushButton#primary:disabled {{
    background: {c.surface_sunk};
    border: 1px solid {c.border};
    color: {c.text_faint};
}}

QPushButton#quiet {{
    background: transparent;
    border: 1px solid transparent;
    color: {c.text_muted};
    padding: {s["xs"]}px {s["sm"]}px;
}}

QPushButton#quiet:hover {{
    background: {c.surface_hover};
    color: {c.text};
}}

QPushButton#quiet:pressed {{
    background: {c.border};
}}

/* Destructive stays neutral at rest and only turns red on approach, so the
   colour is a warning at the moment of acting rather than constant alarm. */
QPushButton#destructive:hover {{
    background: {c.danger_wash};
    border: 1px solid {c.danger};
    color: {c.danger};
}}

QPushButton#destructive:pressed {{
    background: {c.danger_wash};
    border: 1px solid {c.danger};
    color: {c.danger};
}}

/* ------------------------------------------------------------------- lists */

QListWidget {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: {r["lg"]}px;
    outline: 0;
    padding: {s["xs"]}px;
}}

/* Inner radius = outer 11 − 4px list padding. */
QListWidget::item {{
    border-radius: {r["md"]}px;
    color: {c.text};
    padding: {s["sm"]}px {s["md"]}px;
    min-height: 20px;
}}

QListWidget::item:hover {{
    background: {c.surface_hover};
}}

QListWidget::item:selected {{
    background: {c.accent_wash};
    color: {c.text};
}}

QComboBox {{
    background: {c.surface};
    color: {c.text};
    border: 1px solid {c.border_strong};
    border-radius: {r["md"]}px;
    padding: {s["sm"]}px {s["xl"]}px {s["sm"]}px {s["md"]}px;
    min-height: 18px;
}}

QComboBox:hover {{
    border-color: {c.text_faint};
}}

QComboBox:focus {{
    border-color: {c.accent};
    outline: 2px solid {c.focus_ring};
}}

/* The button keeps its width — these combos are editable, and the button is
   the only way to open the popup with a mouse. Only its chrome goes away. */
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    background: transparent;
    border: 0;
    width: {s["xl"]}px;
}}

/* ChevronComboBox paints the real SVG after the styled control. Suppress the
   platform glyph here while keeping the 24px mouse target above. */
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border: 0;
}}

QComboBox QAbstractItemView {{
    background: {c.surface_raised};
    color: {c.text};
    border: 1px solid {c.border_strong};
    selection-background-color: {c.accent_wash};
    selection-color: {c.text};
    outline: 0;
    padding: {s["xs"]}px;
}}

QComboBox QAbstractItemView::item {{
    min-height: 30px;
    padding: {s["xs"]}px {s["sm"]}px;
}}

QTableWidget#indexTable {{
    background: {c.surface};
    border: 1px solid {c.border};
    border-radius: {r["xl"]}px;
    gridline-color: transparent;
    outline: 0;
}}

QTableWidget#indexTable::item {{
    color: {c.text};
    padding: {s["md"]}px {s["lg"]}px;
    border: 0;
    border-bottom: 1px solid {c.border};
}}

QTableWidget#indexTable::item:hover {{
    background: {c.surface_hover};
}}

QTableWidget#indexTable::item:selected {{
    background: {c.accent_wash};
    color: {c.text};
}}

/* A sunk header separates itself from the rows without needing a heavy rule,
   and the caps tracking matches the other micro labels. */
QTableWidget#indexTable QHeaderView::section {{
    background: {c.surface_sunk};
    color: {c.text_faint};
    border: 0;
    border-bottom: 1px solid {c.border};
    padding: {s["sm"]}px {s["lg"]}px;
    font-size: {t["micro"]}px;
    font-weight: 600;
    letter-spacing: {tr["caps"]}px;
}}

/* -------------------------------------------------------------- scrollbars */

QScrollArea {{
    background: transparent;
    border: 0;
}}

/* The handle is inset from the track so it reads as floating over the content
   rather than as a channel cut into the edge of the page. */
QScrollBar:vertical {{
    background: transparent;
    border: 0;
    margin: 0;
    width: 12px;
}}

QScrollBar::handle:vertical {{
    background: {c.border_strong};
    border-radius: 3px;
    min-height: 36px;
    margin: 2px 4px 2px 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {c.text_faint};
}}

QScrollBar::handle:vertical:pressed {{
    background: {c.text_muted};
}}

QScrollBar:horizontal {{
    background: transparent;
    border: 0;
    height: 12px;
    margin: 0;
}}

QScrollBar::handle:horizontal {{
    background: {c.border_strong};
    border-radius: 3px;
    min-width: 36px;
    margin: 4px 2px 4px 2px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {c.text_faint};
}}

QScrollBar::handle:horizontal:pressed {{
    background: {c.text_muted};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    border: 0;
    height: 0;
    width: 0;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

/* ------------------------------------------------------------------ progress */

QProgressBar {{
    background: {c.surface_sunk};
    border: 1px solid {c.border};
    border-radius: {r["xs"]}px;
    max-height: 6px;
    min-height: 6px;
    text-align: center;
}}

QProgressBar::chunk {{
    background: {c.accent};
    border-radius: 2px;
    margin: 0;
}}

/* -------------------------------------------------------------- checkboxes */

/* 8px spacing between box and label, and a 17px box: the extra pixel over 16
   makes the tick sit optically centred rather than a hair high. */
QCheckBox {{
    color: {c.text};
    spacing: {s["sm"]}px;
    padding: {s["xs"]}px 0;
}}

QCheckBox::indicator {{
    background: {c.surface};
    border: 1px solid {c.border_strong};
    border-radius: {r["sm"]}px;
    height: 17px;
    width: 17px;
}}

QCheckBox::indicator:hover {{
    border: 1px solid {c.text_faint};
}}

QCheckBox::indicator:checked {{
    background: {c.accent};
    border: 1px solid {c.accent};
}}

QCheckBox::indicator:focus {{
    border: 1px solid {c.accent};
    outline: 2px solid {c.focus_ring};
}}

QCheckBox::indicator:disabled {{
    background: {c.surface_sunk};
    border: 1px solid {c.border};
}}

/* ------------------------------------------------------------------ dialogs */

QMessageBox, QDialog {{
    background: {c.surface};
}}

QMessageBox QLabel {{
    color: {c.text};
}}

/* Dialog buttons need a wider minimum so "Да"/"Нет" do not become two tiny
   squares, and enough height to clear the 40px hit-area floor with margin. */
QMessageBox QPushButton {{
    min-width: 84px;
    min-height: 22px;
}}

QInputDialog QComboBox, QInputDialog QLineEdit {{
    min-height: 22px;
}}

/* -------------------------------------------------------------- separators */

QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    background: {c.border};
    border: 0;
    max-height: 1px;
}}
"""
