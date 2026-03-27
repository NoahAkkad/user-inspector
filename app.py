import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
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


@dataclass
class ExcelData:
    """Loader for My Chips Excel files."""

    dataframe: Optional[pd.DataFrame] = None

    REQUIRED_COLUMNS = ["UserID", "AppName", "Payout", "DateTime"]
    RENAME_MAP = {
        "UserID": "user_id",
        "AppName": "app",
        "Payout": "payout",
        "DateTime": "date",
    }

    def load(self, path: str) -> pd.DataFrame:
        df = pd.read_excel(path)
        missing = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        df = df[self.REQUIRED_COLUMNS].rename(columns=self.RENAME_MAP).copy()
        df["user_id"] = df["user_id"].astype(str).str.strip()
        df["app"] = df["app"].astype(str).str.strip()
        df["payout"] = pd.to_numeric(df["payout"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        self.dataframe = df
        return df


@dataclass
class PostbackData:
    """Loader for Prime CSV files with postback parsing."""

    dataframe: Optional[pd.DataFrame] = None

    def _extract_user_id(self, raw_user: str) -> str:
        raw_user = (raw_user or "").strip()
        if "-" in raw_user:
            return raw_user.split("-")[-1]
        return raw_user

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

        return {
            "user_id": self._extract_user_id(raw_user),
            "payout": pd.to_numeric(payout, errors="coerce"),
            "reward": pd.to_numeric(reward, errors="coerce"),
            "offer_name": unquote(offer_name),
            "task_name": unquote(task_name),
            "status": unquote(status),
            "app": unquote(app),
        }

    def load(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        if "Postback URL" not in df.columns:
            raise ValueError("Missing required column: Postback URL")

        parsed_df = df["Postback URL"].apply(self._parse_postback_url).apply(pd.Series)
        df = pd.concat([df.copy(), parsed_df], axis=1)
        df["user_id"] = df["user_id"].astype(str).str.strip()

        self.dataframe = df
        return df


class DataModel(QAbstractTableModel):
    def __init__(self, dataframe: Optional[pd.DataFrame] = None) -> None:
        super().__init__()
        self._dataframe = pd.DataFrame() if dataframe is None else dataframe.copy()

    def set_dataframe(self, dataframe: pd.DataFrame) -> None:
        self.beginResetModel()
        self._dataframe = dataframe.copy() if dataframe is not None else pd.DataFrame()
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
            if pd.api.types.is_numeric_dtype(self._dataframe.dtypes.iloc[index.column()]):
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


class ProxyModel(QSortFilterProxyModel):
    SEARCH_FIELDS = ["user_id", "offer_name", "task_name", "app"]

    def __init__(self) -> None:
        super().__init__()
        self.search_field = "global"
        self.search_mode = "contains"
        self.search_query = ""
        self.column_filters: Dict[str, str] = {}
        self.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def update_search(self, field: str, mode: str, query: str) -> None:
        self.search_field = field
        self.search_mode = mode
        self.search_query = query.strip()
        self.invalidateFilter()

    def update_column_filter(self, column: str, expression: str) -> None:
        self.column_filters[column] = expression.strip()
        self.invalidateFilter()

    def clear_filters(self) -> None:
        self.search_field = "global"
        self.search_mode = "contains"
        self.search_query = ""
        self.column_filters.clear()
        self.invalidateFilter()

    def _get_source_value(self, row: int, column_name: str):
        model = self.sourceModel()
        if not isinstance(model, DataModel) or column_name not in model.dataframe.columns:
            return None
        return model.dataframe.iloc[row][column_name]

    def _text_match(self, value: str, query: str, mode: str) -> bool:
        value_l = value.lower()
        query_l = query.lower()
        if mode == "exact":
            return value_l == query_l
        if mode == "starts_with":
            return value_l.startswith(query_l)
        return query_l in value_l

    def _apply_numeric_filter(self, value, expression: str) -> bool:
        if expression == "":
            return True
        number = pd.to_numeric(value, errors="coerce")
        if pd.isna(number):
            return False

        expr = expression.replace(" ", "")
        range_match = re.fullmatch(r"(-?\d+(?:\.\d+)?)\.\.(-?\d+(?:\.\d+)?)", expr)
        if range_match:
            low = float(range_match.group(1))
            high = float(range_match.group(2))
            return low <= float(number) <= high

        op_match = re.fullmatch(r"(<=|>=|=|<|>)(-?\d+(?:\.\d+)?)", expr)
        if op_match:
            op, rhs = op_match.group(1), float(op_match.group(2))
            lhs = float(number)
            return {
                "<": lhs < rhs,
                ">": lhs > rhs,
                "=": lhs == rhs,
                "<=": lhs <= rhs,
                ">=": lhs >= rhs,
            }[op]

        simple_number = re.fullmatch(r"-?\d+(?:\.\d+)?", expr)
        if simple_number:
            return float(number) == float(expr)

        return False

    def _parse_date(self, value):
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        if isinstance(value, datetime):
            return value
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.to_pydatetime()

    def _apply_date_filter(self, value, expression: str) -> bool:
        if expression == "":
            return True
        date_value = self._parse_date(value)
        if date_value is None:
            return False

        expr = expression.strip()
        between_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", expr)
        if between_match:
            start = datetime.fromisoformat(between_match.group(1))
            end = datetime.fromisoformat(between_match.group(2))
            return start.date() <= date_value.date() <= end.date()

        op_match = re.fullmatch(r"(<=|>=|=|<|>)(\d{4}-\d{2}-\d{2})", expr)
        if op_match:
            op, rhs_s = op_match.group(1), op_match.group(2)
            rhs = datetime.fromisoformat(rhs_s).date()
            lhs = date_value.date()
            return {
                "<": lhs < rhs,
                ">": lhs > rhs,
                "=": lhs == rhs,
                "<=": lhs <= rhs,
                ">=": lhs >= rhs,
            }[op]

        exact_match = re.fullmatch(r"\d{4}-\d{2}-\d{2}", expr)
        if exact_match:
            return date_value.date() == datetime.fromisoformat(expr).date()

        return False

    def _column_passes(self, row: int) -> bool:
        model = self.sourceModel()
        if not isinstance(model, DataModel):
            return True

        for column_name, expression in self.column_filters.items():
            if expression == "" or column_name not in model.dataframe.columns:
                continue

            value = self._get_source_value(row, column_name)
            lower_name = column_name.lower()

            if lower_name in {"payout", "reward"}:
                if not self._apply_numeric_filter(value, expression):
                    return False
            elif "date" in lower_name or "time" in lower_name:
                if not self._apply_date_filter(value, expression):
                    return False
            else:
                if expression.lower() == "(blank)":
                    if str(value).strip() != "":
                        return False
                elif expression.lower().startswith("exact:"):
                    exact_val = expression.split(":", 1)[1].strip()
                    if str(value).strip().lower() != exact_val.lower():
                        return False
                else:
                    if expression.lower() not in str(value).lower():
                        return False

        return True

    def _search_passes(self, row: int) -> bool:
        if not self.search_query:
            return True

        model = self.sourceModel()
        if not isinstance(model, DataModel) or model.dataframe.empty:
            return False

        if self.search_field == "global":
            values = [
                str(model.dataframe.iat[row, col_idx])
                for col_idx in range(len(model.dataframe.columns))
            ]
            return any(self._text_match(value, self.search_query, self.search_mode) for value in values)

        if self.search_field not in model.dataframe.columns:
            return False

        value = str(self._get_source_value(row, self.search_field))
        return self._text_match(value, self.search_query, self.search_mode)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        del source_parent
        return self._column_passes(source_row) and self._search_passes(source_row)


class DataTableView(QTableView):
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
        self.setShowGrid(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)

    def copy_selected_cell(self) -> None:
        index = self.currentIndex()
        if not index.isValid():
            return
        text = index.data(Qt.DisplayRole) or ""
        QApplication.clipboard().setText(str(text))


class MainWindow(QMainWindow):
    SEARCH_FIELDS = ["global", "user_id", "offer_name", "task_name", "app"]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("User Inspector")
        self.resize(1460, 900)

        self.excel_data = ExcelData()
        self.postback_data = PostbackData()

        self.model = DataModel()
        self.proxy = ProxyModel()
        self.proxy.setSourceModel(self.model)

        self._filter_inputs: Dict[str, QLineEdit] = {}

        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        root.addWidget(self.create_top_bar())
        root.addWidget(self.create_search_bar())
        root.addWidget(self.create_filter_bar())
        root.addWidget(self.create_table(), 1)
        root.addWidget(self.create_footer())

        copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.table)
        copy_shortcut.activated.connect(self.table.copy_selected_cell)

    def create_top_bar(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self.app_title = QLabel("User Inspector")
        self.app_title.setObjectName("AppTitle")

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["My Chips", "Prime"])

        self.load_button = QPushButton("Load File")
        self.load_button.setProperty("kind", "primary")
        self.load_button.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        self.load_button.clicked.connect(self.load_file)

        layout.addWidget(self.app_title)
        layout.addStretch()
        layout.addWidget(QLabel("Mode"))
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.load_button)
        return frame

    def create_search_bar(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search records...")
        self.search_input.returnPressed.connect(self.apply_search)

        self.search_mode_combo = QComboBox()
        self.search_mode_combo.addItems(["contains", "exact", "starts_with"])

        self.search_field_combo = QComboBox()
        self.search_field_combo.addItems(self.SEARCH_FIELDS)

        self.search_button = QPushButton("Search")
        self.search_button.setProperty("kind", "primary")
        self.search_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.search_button.clicked.connect(self.apply_search)

        self.reset_button = QPushButton("Reset")
        self.reset_button.setProperty("kind", "secondary")
        self.reset_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.reset_button.clicked.connect(self.reset_all_filters)

        layout.addWidget(self.search_input, 4)
        layout.addWidget(self.search_mode_combo, 1)
        layout.addWidget(self.search_field_combo, 1)
        layout.addWidget(self.search_button)
        layout.addWidget(self.reset_button)
        return frame

    def create_filter_bar(self) -> QFrame:
        frame = QFrame()
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(10)

        self.sort_field_combo = QComboBox()
        self.sort_field_combo.addItem("(none)")

        self.sort_order_combo = QComboBox()
        self.sort_order_combo.addItems(["Ascending", "Descending"])

        self.sort_button = QPushButton("Apply Sort")
        self.sort_button.setProperty("kind", "secondary")
        self.sort_button.clicked.connect(self.apply_sort)

        controls.addWidget(QLabel("Sort by"))
        controls.addWidget(self.sort_field_combo, 2)
        controls.addWidget(self.sort_order_combo, 1)
        controls.addWidget(self.sort_button)
        controls.addStretch()

        self.filter_form = QFormLayout()
        self.filter_form.setHorizontalSpacing(12)
        self.filter_form.setVerticalSpacing(8)
        self.filter_form.addRow(
            QLabel(
                "Load a file to enable per-column filters. "
                "Text: contains or exact:value | Numeric: >0.5, <=3, 1..4 | Date: >=2025-01-01, 2025-01-01..2025-01-31"
            )
        )

        outer.addLayout(controls)
        outer.addLayout(self.filter_form)
        return frame

    def create_table(self) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = DataTableView()
        self.table.setModel(self.proxy)
        self.table.selectionModel().selectionChanged.connect(self._update_status)
        self.table.horizontalHeader().sectionClicked.connect(self._autosize_columns)

        layout.addWidget(self.table)
        return frame

    def create_footer(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)

        self.row_count_label = QLabel("Rows: 0")
        self.filter_summary_label = QLabel("Filters: none")
        self.status_label = QLabel("Ready")

        layout.addWidget(self.row_count_label)
        layout.addSpacing(18)
        layout.addWidget(self.filter_summary_label, 1)
        layout.addWidget(self.status_label, 1, Qt.AlignRight)
        return frame

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background-color: #f3f6fb; }

            QFrame {
                background: #ffffff;
                border: 1px solid #e4e9f2;
                border-radius: 12px;
            }

            QLabel { color: #334155; font-size: 13px; }
            QLabel#AppTitle {
                font-size: 20px;
                font-weight: 700;
                color: #0f172a;
                border: none;
            }

            QLineEdit, QComboBox {
                border: 1px solid #d5ddea;
                border-radius: 10px;
                background: #ffffff;
                min-height: 34px;
                padding: 4px 10px;
                color: #0f172a;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #3b82f6;
            }

            QPushButton {
                border: none;
                border-radius: 10px;
                min-height: 36px;
                padding: 4px 14px;
                font-weight: 600;
            }
            QPushButton[kind="primary"] {
                background-color: #2563eb;
                color: #ffffff;
            }
            QPushButton[kind="primary"]:hover { background-color: #1d4ed8; }
            QPushButton[kind="secondary"] {
                background-color: #e9edf5;
                color: #0f172a;
            }
            QPushButton[kind="secondary"]:hover { background-color: #dde5f1; }
            QPushButton:disabled {
                background-color: #cbd5e1;
                color: #64748b;
            }

            QTableView {
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                background: #ffffff;
                alternate-background-color: #f8fafc;
                selection-background-color: #dbeafe;
                selection-color: #1e293b;
                gridline-color: #eff4fa;
                outline: 0;
            }
            QTableView::item { padding: 8px; border: none; }
            QTableView::item:hover { background-color: #edf4ff; }

            QHeaderView::section {
                background-color: #f1f5f9;
                color: #334155;
                border: 0;
                border-bottom: 1px solid #dbe2ee;
                padding: 8px;
                font-size: 12px;
                font-weight: 700;
            }
            """
        )

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def _set_loading_state(self, is_loading: bool) -> None:
        self.load_button.setDisabled(is_loading)
        self.search_button.setDisabled(is_loading)
        self.reset_button.setDisabled(is_loading)
        self.mode_combo.setDisabled(is_loading)
        self.status_label.setText("Loading file..." if is_loading else "Ready")
        QApplication.setOverrideCursor(Qt.WaitCursor) if is_loading else QApplication.restoreOverrideCursor()

    def _clear_filter_rows(self) -> None:
        while self.filter_form.rowCount() > 0:
            self.filter_form.removeRow(0)
        self._filter_inputs.clear()

    def _build_filter_rows(self, columns) -> None:
        self._clear_filter_rows()
        self.sort_field_combo.clear()
        self.sort_field_combo.addItem("(none)")

        if not columns:
            self.filter_form.addRow(QLabel("No columns available."))
            return

        self.sort_field_combo.addItems(columns)
        for col in columns:
            line_edit = QLineEdit()
            lower = col.lower()
            if lower in {"payout", "reward"}:
                line_edit.setPlaceholderText("e.g. >0.5, <=2, 0.5..3")
            elif "date" in lower or "time" in lower:
                line_edit.setPlaceholderText("e.g. >=2025-01-01, 2025-01-01..2025-01-31")
            else:
                line_edit.setPlaceholderText("contains text or exact:value")
            line_edit.textChanged.connect(lambda value, c=col: self._on_column_filter_changed(c, value))
            self.filter_form.addRow(QLabel(col), line_edit)
            self._filter_inputs[col] = line_edit

    def _on_column_filter_changed(self, column: str, value: str) -> None:
        self.proxy.update_column_filter(column, value)
        self._on_proxy_changed()

    def load_file(self) -> None:
        mode = self.mode_combo.currentText()

        if mode == "My Chips":
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Load Excel File",
                "",
                "Excel Files (*.xlsx);;All Files (*)",
            )
        else:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Load CSV File",
                "",
                "CSV Files (*.csv);;All Files (*)",
            )

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
            df = self.excel_data.load(file_path) if mode == "My Chips" else self.postback_data.load(file_path)
            self.model.set_dataframe(df.reset_index(drop=True))
            self.proxy.clear_filters()
            self.search_field_combo.setCurrentText("global")
            self.search_mode_combo.setCurrentText("contains")
            self.search_input.clear()

            self._build_filter_rows(list(df.columns))
            self._autosize_columns()
            self._on_proxy_changed()
            self.status_label.setText(f"Loaded {len(df)} rows")

        except Exception as exc:
            self.show_error(str(exc))
        finally:
            loading.close()
            self._set_loading_state(False)

    def apply_search(self) -> None:
        if self.model.dataframe.empty:
            self.show_error("Please load a file first.")
            return

        self.proxy.update_search(
            self.search_field_combo.currentText(),
            self.search_mode_combo.currentText(),
            self.search_input.text(),
        )
        self._on_proxy_changed()

    def apply_sort(self) -> None:
        if self.model.dataframe.empty:
            return

        field = self.sort_field_combo.currentText()
        if field == "(none)":
            self.table.horizontalHeader().setSortIndicator(-1, Qt.AscendingOrder)
            return

        source_columns = list(self.model.dataframe.columns)
        if field not in source_columns:
            return

        column_index = source_columns.index(field)
        order = Qt.AscendingOrder if self.sort_order_combo.currentText() == "Ascending" else Qt.DescendingOrder
        self.table.sortByColumn(column_index, order)

    def reset_all_filters(self) -> None:
        if self.model.dataframe.empty:
            return

        self.proxy.clear_filters()
        self.search_field_combo.setCurrentText("global")
        self.search_mode_combo.setCurrentText("contains")
        self.search_input.clear()
        self.sort_field_combo.setCurrentIndex(0)
        self.sort_order_combo.setCurrentText("Ascending")

        for line in self._filter_inputs.values():
            line.blockSignals(True)
            line.clear()
            line.blockSignals(False)

        self._on_proxy_changed()

    def _autosize_columns(self) -> None:
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        for idx in range(header.count()):
            header.setSectionResizeMode(idx, QHeaderView.Interactive)
            if self.table.columnWidth(idx) > 360:
                self.table.setColumnWidth(idx, 360)

    def _filter_summary_text(self) -> str:
        parts = []
        if self.proxy.search_query:
            parts.append(
                f"search[{self.proxy.search_field}, {self.proxy.search_mode}]='{self.proxy.search_query}'"
            )

        active_columns = [
            f"{name}:{expr}" for name, expr in self.proxy.column_filters.items() if expr.strip()
        ]
        if active_columns:
            parts.append("columns=" + "; ".join(active_columns))
        return " | ".join(parts) if parts else "none"

    def _on_proxy_changed(self) -> None:
        self.proxy.invalidate()
        self.row_count_label.setText(f"Rows: {self.proxy.rowCount()}")
        self.filter_summary_label.setText(f"Filters: {self._filter_summary_text()}")

    def _update_status(self) -> None:
        index = self.table.currentIndex()
        if not index.isValid():
            self.status_label.setText("Ready")
            return

        header = self.model.headerData(index.column(), Qt.Horizontal)
        value = index.data(Qt.DisplayRole)
        self.status_label.setText(f"Selected [{header}]: {value}")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
