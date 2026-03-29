import sys
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QShortcut,
    QStyle,
    QTableView,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Import qt-material with fallback
try:
    from qt_material import apply_stylesheet
    HAS_QT_MATERIAL = True
except ImportError:
    HAS_QT_MATERIAL = False

# ============================================================================
# Constants
# ============================================================================

class FileSourceMode(Enum):
    """Supported data source file types."""
    MY_CHIPS = "My Chips"
    PRIME = "Prime"


class ColumnNames:
    """Standardized column names for data access."""
    USER_ID = "user_id"
    APP_ID = "app_id"
    PAYOUT = "payout"
    DATE = "date"
    ADVERTISING_ID = "advertising_id"
    POSTBACK_URL = "Postback URL"


class UIConstants:
    """UI dimensions and layout constants."""
    WINDOW_WIDTH = 1600
    WINDOW_HEIGHT = 1000
    ROW_HEIGHT = 34
    MAX_COLUMN_WIDTH = 400
    ROOT_MARGINS = (16, 16, 16, 16)
    SECTION_MARGINS = (14, 12, 14, 12)
    SECTION_SPACING = 12
    FOOTER_MARGINS = (14, 12, 14, 12)
    BUTTON_HEIGHT = 36
    INPUT_HEIGHT = 36


class UIColors:
    """Centralized color palette for styling."""
    BG_MAIN = "#f8f9fa"
    BG_CARD = "#ffffff"
    BORDER_LIGHT = "#e9ecef"
    BORDER_INPUT = "#dee2e6"
    TEXT_PRIMARY = "#1a1a1a"
    TEXT_SECONDARY = "#495057"
    TEXT_MUTED = "#6c757d"
    PRIMARY_BUTTON = "#0078d7"
    PRIMARY_BUTTON_HOVER = "#005fa3"
    PRIMARY_BUTTON_ACTIVE = "#004078"
    SECONDARY_BUTTON = "#f0f0f0"
    SECONDARY_BUTTON_TEXT = "#212529"
    DISABLED_BG = "#e9ecef"
    TABLE_GRID = "#e9ecef"
    TABLE_ALTERNATE = "#f8f9fa"
    TABLE_HOVER = "#e8f4ff"
    TABLE_SELECTED = "#0078d7"
    TABLE_HEADER_BG = "#f0f2f5"
    TABLE_HEADER_TEXT = "#1a1a1a"
    TABLE_HEADER_BORDER = "#dee2e6"
    SUCCESS = "#28a745"
    WARNING = "#ffc107"
    ERROR = "#dc3545"
    INFO = "#17a2b8"


ALL_APPS_FILTER = "All Apps"

ERROR_MESSAGES = {
    "FILE_NOT_LOADED": "Load a file to begin.",
    "USER_ID_REQUIRED": "Please enter a user ID.",
    "ADVERTISING_ID_NOT_FOUND": "The loaded file does not contain an advertising ID column.",
    "ADVERTISING_ID_REQUIRED": "Please enter an advertising ID.",
    "MISSING_COLUMNS": "Missing required columns: {columns}",
    "NO_RESULTS": "No records found matching your search.",
    "INVALID_FILE": "Unable to read file. Please check the file format.",
}

PLACEHOLDER_TEXTS = {
    "USER_ID": "e.g., 264195 or user123",
    "ADVERTISING_ID": "e.g., ad_12345",
}

TOOLTIPS = {
    "LOAD_FILE": "Load Excel or CSV file",
    "SEARCH": "Search records (Enter)",
    "RESET": "Show all data (Esc)",
    "SEARCH_AD": "Search by advertising ID (Enter)",
}

# ============================================================================
# Utility Functions
# ============================================================================


def normalize_id_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Normalize ID columns by filling NaN, converting to string, and stripping whitespace."""
    for col in columns:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
    return df


# ============================================================================
# Data Loaders
# ============================================================================


@dataclass
class ExcelData:
    """Loader for My Chips Excel files."""

    dataframe: Optional[pd.DataFrame] = None

    FILE_COLUMNS = ["UserID", "Payout", "DateTime"]

    def load(self, path: str) -> pd.DataFrame:
        df = pd.read_excel(path)
        missing = [col for col in self.FILE_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        # Keep ALL columns from the original Excel file
        # Extract app_id and user_id from UserID column by splitting on "-"
        raw_user = df["UserID"].astype(str).str.strip()
        df[ColumnNames.APP_ID] = raw_user.str.split("-").str[0].str.strip()
        df[ColumnNames.USER_ID] = raw_user.str.split("-").str[1].str.strip()

        # Rename payout and date columns
        df.rename(columns={
            "Payout": ColumnNames.PAYOUT,
            "DateTime": ColumnNames.DATE,
        }, inplace=True)

        df[ColumnNames.PAYOUT] = pd.to_numeric(df[ColumnNames.PAYOUT], errors="coerce")
        df[ColumnNames.DATE] = pd.to_datetime(df[ColumnNames.DATE], errors="coerce")

        # Filter out numeric-only app_ids (keep only valid app names)
        df = df[~df[ColumnNames.APP_ID].str.isdigit()].copy()

        self.dataframe = df
        return df


@dataclass
class PostbackData:
    """Loader for Prime CSV files with postback parsing."""

    dataframe: Optional[pd.DataFrame] = None

    @staticmethod
    def _extract_user_parts(raw_user: str) -> tuple[str, str]:
        raw_user = (raw_user or "").strip()
        if "-" in raw_user:
            app_id, user_id = raw_user.split("-", 1)
            return app_id.strip(), user_id.strip()
        return "", raw_user

    def _parse_postback_url(self, postback_url: str) -> dict:
        parsed = urlparse(str(postback_url))
        params = parse_qs(parsed.query)

        raw_user = params.get("user", [""])[0]
        payout = params.get("payout", [""])[0]
        reward = params.get("reward", [""])[0]
        offer_name = params.get("offer_name", [""])[0]
        task_name = params.get("task_name", [""])[0]
        status = params.get("status", [""])[0]
        app = params.get("app", [""])[0]
        advertising_id = params.get("advertising_id", [""])[0]
        app_id, user_id = self._extract_user_parts(raw_user)

        return {
            ColumnNames.APP_ID: str(app_id).strip(),
            ColumnNames.USER_ID: str(user_id).strip(),
            ColumnNames.PAYOUT: pd.to_numeric(payout, errors="coerce"),
            "reward": pd.to_numeric(reward, errors="coerce"),
            "offer_name": unquote(offer_name),
            "task_name": unquote(task_name),
            "status": unquote(status),
            "app": unquote(app),
            ColumnNames.ADVERTISING_ID: str(advertising_id).strip(),
        }

    def load(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        if ColumnNames.POSTBACK_URL not in df.columns:
            raise ValueError("Missing required column: Postback URL")

        parsed_df = df[ColumnNames.POSTBACK_URL].apply(self._parse_postback_url).apply(pd.Series)
        df = pd.concat([df.copy(), parsed_df], axis=1)
        df = normalize_id_columns(df, [ColumnNames.USER_ID, ColumnNames.APP_ID, ColumnNames.ADVERTISING_ID])

        self.dataframe = df
        return df


# ============================================================================
# Table Models
# ============================================================================


class DataModel(QAbstractTableModel):
    """Table model for displaying DataFrame data."""

    def __init__(self, dataframe: Optional[pd.DataFrame] = None) -> None:
        super().__init__()
        self._dataframe = pd.DataFrame() if dataframe is None else dataframe.copy()
        self._numeric_columns = set()

    def set_dataframe(self, dataframe: pd.DataFrame) -> None:
        self.beginResetModel()
        self._dataframe = dataframe.copy() if dataframe is not None else pd.DataFrame()
        # Cache numeric column indices for performance
        self._numeric_columns = {
            i for i, dtype in enumerate(self._dataframe.dtypes)
            if pd.api.types.is_numeric_dtype(dtype)
        }
        self.endResetModel()

    @property
    def dataframe(self) -> pd.DataFrame:
        return self._dataframe

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._dataframe)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._dataframe.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or self._dataframe.empty:
            return None

        value = self._dataframe.iat[index.row(), index.column()]

        if role == Qt.DisplayRole:
            if pd.isna(value):
                return ""
            if isinstance(value, pd.Timestamp):
                return value.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(value, float):
                return f"{value:.6g}"
            return str(value)

        if role == Qt.TextAlignmentRole:
            if index.column() in self._numeric_columns:
                return Qt.AlignRight | Qt.AlignVCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if section < len(self._dataframe.columns):
                return str(self._dataframe.columns[section])
            return ""
        return str(section + 1)


class SortFilterProxyModel(QSortFilterProxyModel):
    """Advanced proxy model with column filtering support."""

    def __init__(self) -> None:
        super().__init__()
        self.user_id_query = ""
        self.app_id_query = ALL_APPS_FILTER
        self.advertising_id_query = ""
        self._has_advertising_id = False
        self.setFilterCaseSensitivity(Qt.CaseSensitive)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def setSourceModel(self, model: QAbstractTableModel) -> None:  # noqa: N802
        super().setSourceModel(model)
        if isinstance(model, DataModel):
            self._has_advertising_id = ColumnNames.ADVERTISING_ID in model.dataframe.columns

    def update_user_search(self, user_id: str, app_id: str) -> None:
        self.user_id_query = user_id.strip()
        self.app_id_query = (app_id or ALL_APPS_FILTER).strip()
        self.advertising_id_query = ""
        self.invalidateFilter()

    def update_advertising_search(self, advertising_id: str) -> None:
        self.advertising_id_query = advertising_id.strip()
        self.user_id_query = ""
        self.app_id_query = ALL_APPS_FILTER
        self.invalidateFilter()

    def clear_filters(self) -> None:
        self.user_id_query = ""
        self.app_id_query = ALL_APPS_FILTER
        self.advertising_id_query = ""
        self.invalidateFilter()

    def _get_source_value(self, row: int, column_name: str) -> str:
        model = self.sourceModel()
        if not isinstance(model, DataModel) or column_name not in model.dataframe.columns:
            return ""
        return str(model.dataframe.iloc[row][column_name]).strip()

    def filterAcceptsRow(self, source_row: int, _source_parent: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, DataModel) or model.dataframe.empty:
            return False

        if self.user_id_query:
            row_user_id = self._get_source_value(source_row, ColumnNames.USER_ID)
            if row_user_id != self.user_id_query:
                return False

            if self.app_id_query and self.app_id_query != ALL_APPS_FILTER:
                row_app_id = self._get_source_value(source_row, ColumnNames.APP_ID)
                return row_app_id == self.app_id_query
            return True

        if self.advertising_id_query:
            if not self._has_advertising_id:
                return False
            row_advertising_id = self._get_source_value(source_row, ColumnNames.ADVERTISING_ID)
            return row_advertising_id == self.advertising_id_query

        return True


# ============================================================================
# Table View
# ============================================================================


class DataTableView(QTableView):
    """Professional Excel-like data table with enhanced UX."""

    def __init__(self) -> None:
        super().__init__()
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSortingEnabled(True)
        self.setWordWrap(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setShowGrid(True)

        # Configure header
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionsMovable(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Configure vertical header
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(UIConstants.ROW_HEIGHT)

        # Double-click row signal
        self.doubleClicked.connect(self._on_row_double_click)

    def copy_selected_cell(self) -> None:
        index = self.currentIndex()
        if not index.isValid():
            return
        text = index.data(Qt.DisplayRole) or ""
        QApplication.clipboard().setText(str(text))

    def _on_row_double_click(self, index: QModelIndex) -> None:
        """Handle double-click on table row."""
        if not index.isValid() or not hasattr(self, 'parent') or not self.parent():
            return
        # Emit signal that main window can subscribe to
        self.row_double_clicked.emit(index)

    row_double_clicked = None  # Will be connected in main window


# ============================================================================
# Main Application
# ============================================================================


class MainWindow(QMainWindow):
    """Professional data analysis tool with production-level UX."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("User Inspector")
        self.resize(UIConstants.WINDOW_WIDTH, UIConstants.WINDOW_HEIGHT)

        # Initialize data loaders
        self.excel_data = ExcelData()
        self.postback_data = PostbackData()

        # Initialize models
        self.model = DataModel()
        self.proxy = SortFilterProxyModel()
        self.proxy.setSourceModel(self.model)

        # Data storage
        self.original_df = pd.DataFrame()
        self.is_file_loaded = False

        # Initialize UI - create all elements ONCE
        self._build_ui()
        self._apply_styles()
        self._setup_shortcuts()
        self._setup_empty_state()

    def _setup_empty_state(self) -> None:
        """Setup initial empty state."""
        self.is_file_loaded = False
        self._update_status_message()

    def _build_ui(self) -> None:
        """Build the entire UI (called ONCE during init)."""
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(*UIConstants.ROOT_MARGINS)
        root.setSpacing(14)

        # Build all sections
        root.addLayout(self._build_top_bar_layout(), 0)
        root.addLayout(self._build_search_layout(), 0)
        root.addWidget(self._build_table_frame(), 1)
        root.addLayout(self._build_footer_layout(), 0)

        # Setup copy shortcut
        copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.table)
        copy_shortcut.activated.connect(self.table.copy_selected_cell)

    def _build_top_bar_layout(self) -> QHBoxLayout:
        """Build top navigation bar layout."""
        layout = QHBoxLayout()
        layout.setContentsMargins(*UIConstants.SECTION_MARGINS)
        layout.setSpacing(UIConstants.SECTION_SPACING)

        # App title
        title = QLabel("User Inspector")
        title.setObjectName("AppTitle")

        # Mode selector
        mode_label = QLabel("Source:")
        mode_label.setProperty("weight", "bold")

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([mode.value for mode in FileSourceMode])
        self.mode_combo.setMinimumWidth(120)
        self.mode_combo.setMaximumWidth(150)

        # Load file button
        self.load_button = QPushButton("Load File")
        self.load_button.setProperty("kind", "primary")
        self.load_button.setMinimumHeight(UIConstants.BUTTON_HEIGHT)
        self.load_button.setToolTip(TOOLTIPS["LOAD_FILE"] + " (Ctrl+O)")
        self.load_button.clicked.connect(self.load_file)

        layout.addWidget(title)
        layout.addSpacing(20)
        layout.addWidget(mode_label)
        layout.addWidget(self.mode_combo)
        layout.addStretch()
        layout.addWidget(self.load_button)

        return layout

    def _build_search_layout(self) -> QVBoxLayout:
        """Build search and filter panel layout."""
        layout = QVBoxLayout()
        layout.setContentsMargins(*UIConstants.SECTION_MARGINS)
        layout.setSpacing(10)

        # ========== User ID Search Row ==========
        user_row = QHBoxLayout()
        user_row.setSpacing(UIConstants.SECTION_SPACING)

        user_label = QLabel("Search by User ID:")
        user_label.setProperty("weight", "bold")
        user_label.setMinimumWidth(120)

        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText(PLACEHOLDER_TEXTS["USER_ID"])
        self.user_id_input.setMinimumHeight(UIConstants.INPUT_HEIGHT)
        self.user_id_input.returnPressed.connect(self.apply_user_search)

        app_label = QLabel("Filter by App:")
        app_label.setProperty("weight", "bold")

        self.app_selector = QComboBox()
        self.app_selector.addItem(ALL_APPS_FILTER)
        self.app_selector.setMinimumHeight(UIConstants.INPUT_HEIGHT)

        self.user_search_button = QPushButton("Search")
        self.user_search_button.setProperty("kind", "primary")
        self.user_search_button.setMinimumHeight(UIConstants.BUTTON_HEIGHT)
        self.user_search_button.setToolTip(TOOLTIPS["SEARCH"])
        self.user_search_button.clicked.connect(self.apply_user_search)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setProperty("kind", "secondary")
        self.reset_button.setMinimumHeight(UIConstants.BUTTON_HEIGHT)
        self.reset_button.setToolTip(TOOLTIPS["RESET"] + " (Esc)")
        self.reset_button.clicked.connect(self.reset_view)

        user_row.addWidget(user_label)
        user_row.addWidget(self.user_id_input, 2)
        user_row.addWidget(app_label)
        user_row.addWidget(self.app_selector, 1)
        user_row.addWidget(self.user_search_button)
        user_row.addWidget(self.reset_button)

        # ========== Advertising ID Search Row ==========
        ad_row = QHBoxLayout()
        ad_row.setSpacing(UIConstants.SECTION_SPACING)

        ad_label = QLabel("Search by Advertising ID:")
        ad_label.setProperty("weight", "bold")
        ad_label.setMinimumWidth(150)

        self.advertising_id_input = QLineEdit()
        self.advertising_id_input.setPlaceholderText(PLACEHOLDER_TEXTS["ADVERTISING_ID"])
        self.advertising_id_input.setMinimumHeight(UIConstants.INPUT_HEIGHT)
        self.advertising_id_input.returnPressed.connect(self.apply_advertising_search)

        self.advertising_search_button = QPushButton("Search")
        self.advertising_search_button.setProperty("kind", "primary")
        self.advertising_search_button.setMinimumHeight(UIConstants.BUTTON_HEIGHT)
        self.advertising_search_button.setToolTip(TOOLTIPS["SEARCH_AD"])
        self.advertising_search_button.clicked.connect(self.apply_advertising_search)

        ad_row.addWidget(ad_label)
        ad_row.addWidget(self.advertising_id_input, 3)
        ad_row.addWidget(self.advertising_search_button)
        ad_row.addStretch()

        layout.addLayout(user_row)
        layout.addLayout(ad_row)

        return layout

    def _build_table_frame(self) -> QFrame:
        """Build the main table frame."""
        frame = QFrame()
        frame.setObjectName("TableFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.table = DataTableView()
        self.table.setModel(self.proxy)
        self.table.selectionModel().selectionChanged.connect(self._update_status)

        layout.addWidget(self.table)
        return frame

    def _build_footer_layout(self) -> QHBoxLayout:
        """Build the footer status bar layout."""
        layout = QHBoxLayout()
        layout.setContentsMargins(*UIConstants.FOOTER_MARGINS)
        layout.setSpacing(UIConstants.SECTION_SPACING)

        self.row_count_label = QLabel("Ready")
        self.row_count_label.setProperty("weight", "bold")

        self.filter_summary_label = QLabel("Load a file to begin")
        self.filter_summary_label.setProperty("style", "info")

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(self.row_count_label)
        layout.addSpacing(20)
        layout.addWidget(self.filter_summary_label, 1)
        layout.addWidget(self.status_label)

        return layout

    def _setup_shortcuts(self) -> None:
        """Setup keyboard shortcuts."""
        # Ctrl+O to load file
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self.load_file)
        # Esc to reset
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.reset_view)

    def _apply_styles(self) -> None:
        """Apply comprehensive styling."""
        stylesheet = f"""
            QMainWindow {{
                background-color: {UIColors.BG_MAIN};
            }}

            QFrame {{
                background: {UIColors.BG_CARD};
                border: 1px solid {UIColors.BORDER_LIGHT};
                border-radius: 8px;
            }}

            QLabel {{
                color: {UIColors.TEXT_SECONDARY};
                font-size: 12px;
            }}

            QLabel[weight="bold"] {{
                font-weight: 600;
                color: {UIColors.TEXT_PRIMARY};
            }}

            QLabel[style="info"] {{
                color: {UIColors.INFO};
                font-weight: 500;
            }}

            QLabel#AppTitle {{
                font-size: 20px;
                font-weight: 600;
                color: {UIColors.TEXT_PRIMARY};
            }}

            QLineEdit, QComboBox {{
                background: {UIColors.BG_CARD};
                color: {UIColors.TEXT_PRIMARY};
                border: 1px solid {UIColors.BORDER_INPUT};
                border-radius: 6px;
                padding: 8px 10px;
                font-size: 12px;
                selection-background-color: {UIColors.TABLE_SELECTED};
            }}

            QLineEdit:hover, QComboBox:hover {{
                border: 1px solid {UIColors.PRIMARY_BUTTON};
            }}

            QLineEdit:focus, QComboBox:focus {{
                border: 2px solid {UIColors.PRIMARY_BUTTON};
                padding: 7px 9px;
                background-color: #fafbff;
            }}

            QPushButton[kind="primary"] {{
                background-color: {UIColors.PRIMARY_BUTTON};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 12px;
            }}

            QPushButton[kind="primary"]:hover {{
                background-color: {UIColors.PRIMARY_BUTTON_HOVER};
            }}

            QPushButton[kind="primary"]:pressed {{
                background-color: {UIColors.PRIMARY_BUTTON_ACTIVE};
            }}

            QPushButton[kind="secondary"] {{
                background-color: {UIColors.SECONDARY_BUTTON};
                color: {UIColors.SECONDARY_BUTTON_TEXT};
                border: 1px solid {UIColors.BORDER_INPUT};
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 500;
                font-size: 12px;
            }}

            QPushButton[kind="secondary"]:hover {{
                background-color: #e9ecef;
                border: 1px solid #adb5bd;
            }}

            QPushButton:disabled {{
                background-color: {UIColors.DISABLED_BG};
                color: {UIColors.TEXT_MUTED};
                border: 1px solid transparent;
            }}

            QTableView {{
                background-color: {UIColors.BG_CARD};
                alternate-background-color: {UIColors.TABLE_ALTERNATE};
                gridline-color: {UIColors.TABLE_GRID};
                border: none;
                outline: none;
            }}

            QTableView::item {{
                padding: 6px 8px;
                color: {UIColors.TEXT_PRIMARY};
            }}

            QTableView::item:hover {{
                background-color: {UIColors.TABLE_HOVER};
            }}

            QTableView::item:selected {{
                background-color: {UIColors.TABLE_SELECTED};
                color: white;
                font-weight: 500;
            }}

            QHeaderView::section {{
                background-color: {UIColors.TABLE_HEADER_BG};
                color: {UIColors.TABLE_HEADER_TEXT};
                border: none;
                border-bottom: 1px solid {UIColors.TABLE_HEADER_BORDER};
                border-right: 1px solid {UIColors.TABLE_HEADER_BORDER};
                padding: 8px 10px;
                font-size: 11px;
                font-weight: 600;
                text-align: left;
            }}

            QHeaderView::section:hover {{
                background-color: #e8eaed;
            }}

            QScrollBar:vertical {{
                width: 10px;
                background: transparent;
            }}

            QScrollBar::handle:vertical {{
                background: {UIColors.BORDER_INPUT};
                border-radius: 5px;
                min-height: 20px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: {UIColors.BORDER_LIGHT};
            }}

            QScrollBar:horizontal {{
                height: 10px;
                background: transparent;
            }}

            QScrollBar::handle:horizontal {{
                background: {UIColors.BORDER_INPUT};
                border-radius: 5px;
                min-width: 20px;
            }}

            QScrollBar::handle:horizontal:hover {{
                background: {UIColors.BORDER_LIGHT};
            }}
        """

        self.setStyleSheet(stylesheet)

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message: str) -> None:
        QMessageBox.information(self, "Info", message)

    def _update_status_message(self) -> None:
        """Update status message based on state."""
        if not self.is_file_loaded:
            self.filter_summary_label.setText("Load a file to begin")
            self.row_count_label.setText("Ready")
            return

        if self.proxy.rowCount() == 0:
            self.filter_summary_label.setText("No results found")
            self.row_count_label.setText("Showing 0 records")
        else:
            total = len(self.model.dataframe)
            displayed = self.proxy.rowCount()
            if total == displayed:
                self.row_count_label.setText(f"Showing {displayed:,} records")
                self.filter_summary_label.setText("Filters: none active")
            else:
                self.row_count_label.setText(f"Showing {displayed:,} of {total:,} records")
                self.filter_summary_label.setText(f"Filters: {self._filter_summary_text()}")

    def _set_loading_state(self, is_loading: bool) -> None:
        """Set UI state during file loading."""
        buttons = [
            "load_button", "user_search_button", "advertising_search_button",
            "reset_button", "mode_combo", "app_selector", "user_id_input", "advertising_id_input"
        ]

        for btn_name in buttons:
            if hasattr(self, btn_name):
                getattr(self, btn_name).setDisabled(is_loading)

        if is_loading:
            self.row_count_label.setText("Loading...")
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            if self.is_file_loaded:
                self._update_status_message()
            QApplication.restoreOverrideCursor()

    def _populate_app_selector(self, df: pd.DataFrame) -> None:
        """Populate app selector dropdown."""
        self.app_selector.clear()
        self.app_selector.addItem(ALL_APPS_FILTER)

        if ColumnNames.APP_ID not in df.columns:
            return

        unique_apps = sorted(df[ColumnNames.APP_ID].dropna().unique())[:1000]
        self.app_selector.addItems(unique_apps)

    def _get_file_path(self, mode: FileSourceMode) -> str:
        """Get file path from user."""
        file_types = {
            FileSourceMode.MY_CHIPS: "Excel Files (*.xlsx);;All Files (*)",
            FileSourceMode.PRIME: "CSV Files (*.csv);;All Files (*)",
        }
        dialog_names = {
            FileSourceMode.MY_CHIPS: "Load My Chips Data File",
            FileSourceMode.PRIME: "Load Prime CSV File",
        }
        file_path, _ = QFileDialog.getOpenFileName(
            self, dialog_names[mode], "", file_types[mode]
        )
        return file_path

    def load_file(self) -> None:
        """Load a data file."""
        mode_text = self.mode_combo.currentText()
        mode = FileSourceMode(mode_text)
        file_path = self._get_file_path(mode)

        if not file_path:
            return

        loading = QProgressDialog("Processing file...", None, 0, 0, self)
        loading.setWindowTitle("Loading")
        loading.setWindowModality(Qt.WindowModal)
        loading.setCancelButton(None)
        loading.show()

        self._set_loading_state(True)
        QApplication.processEvents()

        try:
            df = (
                self.excel_data.load(file_path)
                if mode == FileSourceMode.MY_CHIPS
                else self.postback_data.load(file_path)
            )
            df = df.reset_index(drop=True)

            self.original_df = df.copy()
            self.model.set_dataframe(df)
            self.proxy.clear_filters()
            self.user_id_input.clear()
            self.advertising_id_input.clear()
            self.is_file_loaded = True

            print(f"✓ Successfully loaded {len(df):,} records")

            self._populate_app_selector(df)
            self._autosize_columns()
            self._update_status_message()

        except Exception as exc:
            self.is_file_loaded = False
            self.show_error(f"{ERROR_MESSAGES.get('INVALID_FILE', 'Error')}\n{str(exc)}")
        finally:
            loading.close()
            self._set_loading_state(False)

    def apply_user_search(self) -> None:
        """Search by user ID."""
        if not self.is_file_loaded:
            self.show_error(ERROR_MESSAGES["FILE_NOT_LOADED"])
            return

        user_id = self.user_id_input.text().strip()
        if not user_id:
            self.show_error(ERROR_MESSAGES["USER_ID_REQUIRED"])
            return

        selected_app = self.app_selector.currentText()
        self.advertising_id_input.clear()
        self.proxy.update_user_search(user_id=user_id, app_id=selected_app)
        self._update_status_message()

    def apply_advertising_search(self) -> None:
        """Search by advertising ID."""
        if not self.is_file_loaded:
            self.show_error(ERROR_MESSAGES["FILE_NOT_LOADED"])
            return

        if ColumnNames.ADVERTISING_ID not in self.model.dataframe.columns:
            self.show_error(ERROR_MESSAGES["ADVERTISING_ID_NOT_FOUND"])
            return

        advertising_id = self.advertising_id_input.text().strip()
        if not advertising_id:
            self.show_error(ERROR_MESSAGES["ADVERTISING_ID_REQUIRED"])
            return

        self.user_id_input.clear()
        self.app_selector.setCurrentText(ALL_APPS_FILTER)
        self.proxy.update_advertising_search(advertising_id)
        self._update_status_message()

    def reset_view(self) -> None:
        """Reset to show all data."""
        if not self.is_file_loaded:
            return

        self.model.set_dataframe(self.original_df)
        self.proxy.clear_filters()
        self.user_id_input.clear()
        self.advertising_id_input.clear()
        self.app_selector.setCurrentText(ALL_APPS_FILTER)
        self._update_status_message()

    def _autosize_columns(self) -> None:
        """Auto-size table columns."""
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        for idx in range(header.count()):
            width = self.table.columnWidth(idx)
            if width > UIConstants.MAX_COLUMN_WIDTH:
                self.table.setColumnWidth(idx, UIConstants.MAX_COLUMN_WIDTH)

    def _filter_summary_text(self) -> str:
        """Generate filter summary text."""
        if not self.proxy.user_id_query and not self.proxy.advertising_id_query:
            return "none"

        if self.proxy.user_id_query:
            if self.proxy.app_id_query == ALL_APPS_FILTER:
                return f"user_id = '{self.proxy.user_id_query}'"
            return f"user_id = '{self.proxy.user_id_query}' & app = '{self.proxy.app_id_query}'"

        return f"ad_id = '{self.proxy.advertising_id_query}'"

    def _update_status(self) -> None:
        """Update status bar with selected cell info."""
        index = self.table.currentIndex()
        if not index.isValid():
            self.status_label.setText("")
            return

        header = self.model.headerData(index.column(), Qt.Horizontal)
        value = index.data(Qt.DisplayRole)
        self.status_label.setText(f"[{header}]: {value}")


def main() -> None:
    import warnings
    import os

    # Suppress warnings
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = ''
    warnings.filterwarnings('ignore')

    app = QApplication(sys.argv)

    # Apply qt-material theme if available
    if HAS_QT_MATERIAL:
        try:
            apply_stylesheet(app, theme='light_blue.xml', invert_secondary=False)
        except Exception:
            pass

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
