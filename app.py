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


ALL_APPS_FILTER = "All Apps"

ERROR_MESSAGES = {
    "FILE_NOT_LOADED": "Please load a file first.",
    "USER_ID_REQUIRED": "Please enter a user ID.",
    "ADVERTISING_ID_NOT_FOUND": "The loaded file does not contain an advertising ID column.",
    "ADVERTISING_ID_REQUIRED": "Please enter an advertising ID.",
    "MISSING_COLUMNS": "Missing required columns: {columns}",
    "NO_RESULTS": "No records found for the selected criteria.",
}

PLACEHOLDER_TEXTS = {
    "USER_ID": "e.g., 264195, user123",
    "ADVERTISING_ID": "e.g., ad_12345",
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
        self.setColumnHidden(0, False)

        # Configure header
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionsMovable(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        # Configure vertical header
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(UIConstants.ROW_HEIGHT)

    def copy_selected_cell(self) -> None:
        index = self.currentIndex()
        if not index.isValid():
            return
        text = index.data(Qt.DisplayRole) or ""
        QApplication.clipboard().setText(str(text))


# ============================================================================
# Main Application
# ============================================================================


class MainWindow(QMainWindow):
    """Professional data analysis tool with clean, intuitive UI."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("User Inspector")
        self.resize(UIConstants.WINDOW_WIDTH, UIConstants.WINDOW_HEIGHT)

        self.excel_data = ExcelData()
        self.postback_data = PostbackData()

        self.model = DataModel()
        self.proxy = SortFilterProxyModel()
        self.proxy.setSourceModel(self.model)

        self.original_df = pd.DataFrame()

        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(*UIConstants.ROOT_MARGINS)
        root.setSpacing(14)

        # Build sections
        root.addWidget(self._build_top_bar(), 0)
        root.addWidget(self._build_search_section(), 0)
        root.addWidget(self._build_table(), 1)
        root.addWidget(self._build_footer(), 0)

        # Copy shortcut
        copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.table)
        copy_shortcut.activated.connect(self.table.copy_selected_cell)

    def _create_section_frame(self) -> tuple[QFrame, QHBoxLayout]:
        """Create a styled section frame with horizontal layout."""
        frame = QFrame()
        frame.setObjectName("SectionFrame")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(*UIConstants.SECTION_MARGINS)
        layout.setSpacing(UIConstants.SECTION_SPACING)
        return frame, layout

    def _build_top_bar(self) -> QFrame:
        """Build the top navigation bar."""
        frame, layout = self._create_section_frame()

        # App title
        title = QLabel("User Inspector")
        title.setObjectName("AppTitle")
        title.setProperty("size", "large")

        # Mode selector
        mode_label = QLabel("Source:")
        mode_label.setProperty("weight", "bold")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([mode.value for mode in FileSourceMode])
        self.mode_combo.setMinimumWidth(120)
        self.mode_combo.setMaximumWidth(150)

        # Load button
        self.load_button = QPushButton("📁 Load File")
        self.load_button.setProperty("kind", "primary")
        self.load_button.setMinimumHeight(UIConstants.BUTTON_HEIGHT)
        self.load_button.setToolTip("Load a new data file")
        self.load_button.clicked.connect(self.load_file)

        layout.addWidget(title)
        layout.addSpacing(20)
        layout.addWidget(mode_label)
        layout.addWidget(self.mode_combo)
        layout.addStretch()
        layout.addWidget(self.load_button)

        return frame

    def _build_search_section(self) -> QFrame:
        """Build the search and filter panel."""
        frame = QFrame()
        frame.setObjectName("SearchSection")
        main_layout = QVBoxLayout(frame)
        main_layout.setContentsMargins(*UIConstants.SECTION_MARGINS)
        main_layout.setSpacing(10)

        # User ID search row
        user_row, user_layout = self._create_section_frame()
        user_row.setObjectName("SearchRow")

        # User ID section
        user_label = QLabel("Search by User ID:")
        user_label.setProperty("weight", "bold")
        user_label.setMinimumWidth(120)

        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText(PLACEHOLDER_TEXTS["USER_ID"])
        self.user_id_input.setMinimumHeight(UIConstants.INPUT_HEIGHT)
        self.user_id_input.returnPressed.connect(self.apply_user_search)

        # App filter
        app_label = QLabel("Filter by App:")
        app_label.setProperty("weight", "bold")
        self.app_selector = QComboBox()
        self.app_selector.addItem(ALL_APPS_FILTER)
        self.app_selector.setMinimumHeight(UIConstants.INPUT_HEIGHT)

        # Search button
        self.user_search_button = QPushButton("🔍 Search")
        self.user_search_button.setProperty("kind", "primary")
        self.user_search_button.setMinimumHeight(UIConstants.BUTTON_HEIGHT)
        self.user_search_button.setToolTip("Search for user records")
        self.user_search_button.clicked.connect(self.apply_user_search)

        # Reset button
        self.reset_button = QPushButton("↺ Reset")
        self.reset_button.setProperty("kind", "secondary")
        self.reset_button.setMinimumHeight(UIConstants.BUTTON_HEIGHT)
        self.reset_button.setToolTip("Show all records")
        self.reset_button.clicked.connect(self.reset_view)

        user_layout.addWidget(user_label)
        user_layout.addWidget(self.user_id_input, 2)
        user_layout.addWidget(app_label)
        user_layout.addWidget(self.app_selector, 1)
        user_layout.addWidget(self.user_search_button)
        user_layout.addWidget(self.reset_button)

        # Advertising ID search row (secondary)
        ad_row, ad_layout = self._create_section_frame()
        ad_row.setObjectName("SecondarySearchRow")

        ad_label = QLabel("Search by Advertising ID:")
        ad_label.setProperty("weight", "bold")
        ad_label.setMinimumWidth(150)

        self.advertising_id_input = QLineEdit()
        self.advertising_id_input.setPlaceholderText(PLACEHOLDER_TEXTS["ADVERTISING_ID"])
        self.advertising_id_input.setMinimumHeight(UIConstants.INPUT_HEIGHT)
        self.advertising_id_input.returnPressed.connect(self.apply_advertising_search)

        self.advertising_search_button = QPushButton("🔍 Search")
        self.advertising_search_button.setProperty("kind", "primary")
        self.advertising_search_button.setMinimumHeight(UIConstants.BUTTON_HEIGHT)
        self.advertising_search_button.setToolTip("Search by advertising ID")
        self.advertising_search_button.clicked.connect(self.apply_advertising_search)

        ad_layout.addWidget(ad_label)
        ad_layout.addWidget(self.advertising_id_input, 3)
        ad_layout.addWidget(self.advertising_search_button)
        ad_layout.addStretch()

        main_layout.addLayout(user_layout)
        main_layout.addLayout(ad_layout)

        return frame

    def _build_table(self) -> QFrame:
        """Build the main data table."""
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

    def _build_footer(self) -> QFrame:
        """Build the footer with status information."""
        frame, layout = self._create_section_frame()
        frame.setObjectName("FooterFrame")

        # Row count
        self.row_count_label = QLabel("Records: 0")
        self.row_count_label.setProperty("weight", "bold")

        # Filter summary
        self.filter_summary_label = QLabel("Filters: none")

        # Status indicator
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setProperty("weight", "bold")

        layout.addWidget(self.row_count_label)
        layout.addSpacing(20)
        layout.addWidget(self.filter_summary_label, 1)
        layout.addWidget(self.status_label)

        return frame

    def _apply_styles(self) -> None:
        """Apply comprehensive styling to all UI elements."""
        stylesheet = f"""
            QMainWindow {{
                background-color: {UIColors.BG_MAIN};
            }}

            /* Section Frames */
            #SectionFrame, #SearchRow, #SecondarySearchRow, #TableFrame, #FooterFrame {{
                background: {UIColors.BG_CARD};
                border: 1px solid {UIColors.BORDER_LIGHT};
                border-radius: 8px;
            }}

            /* Typography */
            QLabel {{
                color: {UIColors.TEXT_SECONDARY};
                font-size: 12px;
            }}

            QLabel[size="large"] {{
                font-size: 20px;
                font-weight: 600;
                color: {UIColors.TEXT_PRIMARY};
            }}

            QLabel[weight="bold"] {{
                font-weight: 600;
                color: {UIColors.TEXT_PRIMARY};
            }}

            /* Inputs */
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

            /* Primary Buttons */
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

            /* Secondary Buttons */
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

            /* Disabled Buttons */
            QPushButton:disabled {{
                background-color: {UIColors.DISABLED_BG};
                color: {UIColors.TEXT_MUTED};
                border: 1px solid transparent;
            }}

            /* Table Styling */
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

            /* Table Header */
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

            QHeaderView::up-arrow, QHeaderView::down-arrow {{
                width: 6px;
                height: 6px;
                margin-right: 3px;
            }}
        """

        self.setStyleSheet(stylesheet)

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def show_info(self, message: str) -> None:
        QMessageBox.information(self, "Info", message)

    def _set_loading_state(self, is_loading: bool) -> None:
        self.load_button.setDisabled(is_loading)
        self.user_search_button.setDisabled(is_loading)
        self.advertising_search_button.setDisabled(is_loading)
        self.reset_button.setDisabled(is_loading)
        self.mode_combo.setDisabled(is_loading)
        self.app_selector.setDisabled(is_loading)
        self.user_id_input.setDisabled(is_loading)
        self.advertising_id_input.setDisabled(is_loading)

        if is_loading:
            self.status_label.setText("⏳ Loading...")
            self.status_label.setProperty("status", "loading")
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            self.status_label.setText("✓ Ready")
            self.status_label.setProperty("status", "ready")
            QApplication.restoreOverrideCursor()

    def _populate_app_selector(self, df: pd.DataFrame) -> None:
        """Populate the app selector dropdown with unique app IDs."""
        self.app_selector.clear()
        self.app_selector.addItem(ALL_APPS_FILTER)

        if ColumnNames.APP_ID not in df.columns:
            return

        unique_apps = sorted(df[ColumnNames.APP_ID].dropna().unique())[:1000]
        self.app_selector.addItems(unique_apps)

    def _get_file_path(self, mode: FileSourceMode) -> str:
        """Get file path based on selected source mode."""
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

    def _check_file_loaded(self) -> bool:
        """Check if a file is loaded."""
        if self.model.dataframe.empty:
            self.show_error(ERROR_MESSAGES["FILE_NOT_LOADED"])
            return False
        return True

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
        loading.setStyleSheet(f"QProgressDialog {{ background-color: {UIColors.BG_CARD}; }}")
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

            if mode == FileSourceMode.MY_CHIPS:
                print(f"✓ Loaded {len(df)} records from {mode_text}")
                print(f"  Sample apps: {', '.join(df[ColumnNames.APP_ID].unique()[:5])}")

            self._populate_app_selector(df)
            self._autosize_columns()
            self._on_proxy_changed()
            self.status_label.setText(f"✓ Loaded {len(df):,} records")

        except Exception as exc:
            self.show_error(f"Failed to load file:\n{str(exc)}")
        finally:
            loading.close()
            self._set_loading_state(False)

    def apply_user_search(self) -> None:
        """Search by user ID and app."""
        if not self._check_file_loaded():
            return

        user_id = self.user_id_input.text().strip()
        if not user_id:
            self.show_error(ERROR_MESSAGES["USER_ID_REQUIRED"])
            return

        selected_app = self.app_selector.currentText()
        self.advertising_id_input.clear()
        self.proxy.update_user_search(user_id=user_id, app_id=selected_app)
        self._on_proxy_changed()

        if self.proxy.rowCount() == 0:
            self.show_error(ERROR_MESSAGES["NO_RESULTS"])

    def apply_advertising_search(self) -> None:
        """Search by advertising ID."""
        if not self._check_file_loaded():
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
        self._on_proxy_changed()

        if self.proxy.rowCount() == 0:
            self.show_error(ERROR_MESSAGES["NO_RESULTS"])

    def reset_view(self) -> None:
        """Reset to show all data."""
        if self.original_df.empty:
            self.show_error(ERROR_MESSAGES["FILE_NOT_LOADED"])
            return

        self.model.set_dataframe(self.original_df)
        self.proxy.clear_filters()
        self.user_id_input.clear()
        self.advertising_id_input.clear()
        self.app_selector.setCurrentText(ALL_APPS_FILTER)
        self._on_proxy_changed()
        self.status_label.setText("✓ Showing all records")

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

    def _on_proxy_changed(self) -> None:
        """Update UI when proxy model changes."""
        self.proxy.invalidate()
        row_count = self.proxy.rowCount()
        self.row_count_label.setText(f"Records: {row_count:,}")
        self.filter_summary_label.setText(f"Filters: {self._filter_summary_text()}")

    def _update_status(self) -> None:
        """Update status bar with selected cell info."""
        index = self.table.currentIndex()
        if not index.isValid():
            return

        header = self.model.headerData(index.column(), Qt.Horizontal)
        value = index.data(Qt.DisplayRole)
        self.status_label.setText(f"[{header}]: {value}")


def main() -> None:
    import warnings
    import os

    # Suppress warnings
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = ''
    warnings.filterwarnings('ignore', category=DeprecationWarning)

    app = QApplication(sys.argv)

    # Apply qt-material theme if available
    if HAS_QT_MATERIAL:
        try:
            apply_stylesheet(app, theme='light_blue.xml', invert_secondary=False)
        except Exception:
            pass  # Fall back to custom styling

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
