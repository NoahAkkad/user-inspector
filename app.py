import re
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
from PyQt5.QtCore import QAbstractTableModel, QSortFilterProxyModel, Qt, QModelIndex
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
    QHeaderView,
    QShortcut,
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
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.verticalHeader().setVisible(False)

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
        self.setWindowTitle("Professional Data Analysis Tool")
        self.resize(1400, 840)

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
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["My Chips", "Prime"])

        self.load_button = QPushButton("Load File")
        self.load_button.clicked.connect(self.load_file)

        top_bar.addWidget(QLabel("Mode"))
        top_bar.addWidget(self.mode_combo)
        top_bar.addStretch()
        top_bar.addWidget(self.load_button)

        search_group = QGroupBox("Advanced Search")
        search_layout = QHBoxLayout(search_group)
        search_layout.setSpacing(10)

        self.search_field_combo = QComboBox()
        self.search_field_combo.addItems([
            "global",
            "user_id",
            "offer_name",
            "task_name",
            "app",
        ])

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search value")

        self.search_mode_combo = QComboBox()
        self.search_mode_combo.addItems(["contains", "exact", "starts_with"])

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.apply_search)

        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_all_filters)

        search_layout.addWidget(QLabel("Field"))
        search_layout.addWidget(self.search_field_combo)
        search_layout.addWidget(QLabel("Query"))
        search_layout.addWidget(self.search_input, 1)
        search_layout.addWidget(QLabel("Mode"))
        search_layout.addWidget(self.search_mode_combo)
        search_layout.addWidget(self.search_button)
        search_layout.addWidget(self.reset_button)

        filter_group = QGroupBox("Column Filters")
        self.filter_form = QFormLayout(filter_group)
        self.filter_form.setHorizontalSpacing(10)
        self.filter_form.setVerticalSpacing(8)
        self.filter_form.addRow(
            QLabel("Load a file to enable per-column filters.\n"
                   "Text: contains or 'exact:value' | Numeric: >0.5, <=3, 1..4 | Date: >=2025-01-01, 2025-01-01..2025-01-31")
        )

        table_frame = QFrame()
        table_layout = QVBoxLayout(table_frame)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.table = DataTableView()
        self.table.setModel(self.proxy)
        self.table.selectionModel().selectionChanged.connect(self._update_status)
        self.table.horizontalHeader().sectionClicked.connect(self._autosize_columns)

        self.row_count_label = QLabel("Rows: 0")
        self.status_label = QLabel("Ready")

        footer = QHBoxLayout()
        footer.addWidget(self.row_count_label)
        footer.addStretch()
        footer.addWidget(self.status_label)

        table_layout.addWidget(self.table)
        table_layout.addLayout(footer)

        root.addLayout(top_bar)
        root.addWidget(search_group)
        root.addWidget(filter_group)
        root.addWidget(table_frame, 1)

        copy_shortcut = QShortcut(QKeySequence("Ctrl+C"), self.table)
        copy_shortcut.activated.connect(self.table.copy_selected_cell)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background-color: #f5f7fb; }
            QLabel { color: #2f3542; font-size: 12px; }
            QGroupBox {
                border: 1px solid #dde3ee;
                border-radius: 8px;
                margin-top: 8px;
                padding: 10px;
                background: #ffffff;
                font-weight: 600;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px; }
            QLineEdit, QComboBox {
                border: 1px solid #ced6e0;
                border-radius: 6px;
                background: #ffffff;
                min-height: 30px;
                padding: 4px 8px;
            }
            QPushButton {
                border: none;
                border-radius: 6px;
                background-color: #2f80ed;
                color: #ffffff;
                font-weight: 600;
                min-height: 30px;
                padding: 4px 12px;
            }
            QPushButton:hover { background-color: #1d6fd1; }
            QTableView {
                border: 1px solid #dde3ee;
                border-radius: 8px;
                background: #ffffff;
                gridline-color: #edf1f7;
                selection-background-color: #d7ebff;
                selection-color: #0d1b2a;
                alternate-background-color: #f8fbff;
            }
            QHeaderView::section {
                background-color: #eef3fa;
                border: 0;
                border-right: 1px solid #d9e0ec;
                border-bottom: 1px solid #d9e0ec;
                padding: 6px;
                font-weight: 600;
            }
            """
        )

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def _clear_filter_rows(self) -> None:
        while self.filter_form.rowCount() > 0:
            self.filter_form.removeRow(0)
        self._filter_inputs.clear()

    def _build_filter_rows(self, columns) -> None:
        self._clear_filter_rows()
        if not columns:
            self.filter_form.addRow(QLabel("No columns available."))
            return

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

        loading = QProgressDialog("Loading file...", None, 0, 0, self)
        loading.setWindowTitle("Please wait")
        loading.setWindowModality(Qt.WindowModal)
        loading.setCancelButton(None)
        loading.show()
        QApplication.processEvents()

        try:
            if mode == "My Chips":
                df = self.excel_data.load(file_path)
            else:
                df = self.postback_data.load(file_path)

            self.model.set_dataframe(df.reset_index(drop=True))
            self.proxy.clear_filters()
            self.search_field_combo.setCurrentText("global")
            self.search_mode_combo.setCurrentText("contains")
            self.search_input.clear()

            self._build_filter_rows(list(df.columns))
            self._autosize_columns()
            self._on_proxy_changed()
            self.status_label.setText(f"Loaded: {file_path}")

        except Exception as exc:
            self.show_error(str(exc))
        finally:
            loading.close()

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

    def reset_all_filters(self) -> None:
        if self.model.dataframe.empty:
            return

        self.proxy.clear_filters()
        self.search_field_combo.setCurrentText("global")
        self.search_mode_combo.setCurrentText("contains")
        self.search_input.clear()
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

    def _on_proxy_changed(self) -> None:
        self.proxy.invalidate()
        self.row_count_label.setText(f"Rows: {self.proxy.rowCount()}")

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
