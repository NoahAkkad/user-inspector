import sys
from dataclasses import dataclass
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


@dataclass
class ExcelData:
    """Loader for My Chips Excel files."""

    dataframe: Optional[pd.DataFrame] = None

    REQUIRED_COLUMNS = ["UserID", "AppName", "Payout", "DateTime"]
    RENAME_MAP = {
        "UserID": "user_id",
        "AppName": "app_id",
        "Payout": "payout",
        "DateTime": "date",
    }

    def load(self, path: str) -> pd.DataFrame:
        df = pd.read_excel(path)
        missing = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {', '.join(missing)}")

        df = df[self.REQUIRED_COLUMNS].rename(columns=self.RENAME_MAP).copy()
        df["user_id"] = df["user_id"].fillna("").astype(str).str.strip()
        df["app_id"] = df["app_id"].fillna("").astype(str).str.strip()

        df["payout"] = pd.to_numeric(df["payout"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

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
            "app_id": str(app_id).strip(),
            "user_id": str(user_id).strip(),
            "payout": pd.to_numeric(payout, errors="coerce"),
            "reward": pd.to_numeric(reward, errors="coerce"),
            "offer_name": unquote(offer_name),
            "task_name": unquote(task_name),
            "status": unquote(status),
            "app": unquote(app),
            "advertising_id": str(advertising_id).strip(),
        }

    def load(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(path)
        if "Postback URL" not in df.columns:
            raise ValueError("Missing required column: Postback URL")

        parsed_df = df["Postback URL"].apply(self._parse_postback_url).apply(pd.Series)
        df = pd.concat([df.copy(), parsed_df], axis=1)
        df["user_id"] = df["user_id"].fillna("").astype(str).str.strip()
        df["app_id"] = df["app_id"].fillna("").astype(str).str.strip()
        if "advertising_id" in df.columns:
            df["advertising_id"] = df["advertising_id"].fillna("").astype(str).str.strip()

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
    def __init__(self) -> None:
        super().__init__()
        self.user_id_query = ""
        self.app_id_query = "All"
        self.advertising_id_query = ""
        self.setFilterCaseSensitivity(Qt.CaseSensitive)
        self.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def update_user_search(self, user_id: str, app_id: str) -> None:
        self.user_id_query = user_id.strip()
        self.app_id_query = (app_id or "All").strip()
        self.advertising_id_query = ""
        self.invalidateFilter()

    def update_advertising_search(self, advertising_id: str) -> None:
        self.advertising_id_query = advertising_id.strip()
        self.user_id_query = ""
        self.app_id_query = "All"
        self.invalidateFilter()

    def clear_filters(self) -> None:
        self.user_id_query = ""
        self.app_id_query = "All"
        self.advertising_id_query = ""
        self.invalidateFilter()

    def _get_source_value(self, row: int, column_name: str) -> str:
        model = self.sourceModel()
        if not isinstance(model, DataModel) or column_name not in model.dataframe.columns:
            return ""
        return str(model.dataframe.iloc[row][column_name]).strip()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        del source_parent
        model = self.sourceModel()
        if not isinstance(model, DataModel) or model.dataframe.empty:
            return False

        if self.user_id_query:
            row_user_id = self._get_source_value(source_row, "user_id")
            if row_user_id != self.user_id_query:
                return False

            if self.app_id_query and self.app_id_query != "All":
                row_app_id = self._get_source_value(source_row, "app_id")
                return row_app_id == self.app_id_query
            return True

        if self.advertising_id_query:
            if "advertising_id" not in model.dataframe.columns:
                return False
            row_advertising_id = self._get_source_value(source_row, "advertising_id")
            return row_advertising_id == self.advertising_id_query

        return True


class DataTableView(QTableView):
    def __init__(self) -> None:
        super().__init__()
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSortingEnabled(False)
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
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("User Inspector")
        self.resize(1200, 820)

        self.excel_data = ExcelData()
        self.postback_data = PostbackData()

        self.model = DataModel()
        self.proxy = ProxyModel()
        self.proxy.setSourceModel(self.model)

        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        root.addWidget(self.create_top_bar())
        root.addWidget(self.create_user_search_section())
        root.addWidget(self.create_advertising_search_section())
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

    def create_user_search_section(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        layout.addWidget(QLabel("User ID"))
        self.user_id_input = QLineEdit()
        self.user_id_input.setPlaceholderText("Enter user_id (e.g. 97344)")
        self.user_id_input.returnPressed.connect(self.apply_user_search)

        layout.addWidget(self.user_id_input, 2)

        layout.addWidget(QLabel("App"))
        self.app_selector = QComboBox()
        self.app_selector.addItem("All")
        layout.addWidget(self.app_selector, 1)

        self.user_search_button = QPushButton("Search")
        self.user_search_button.setProperty("kind", "primary")
        self.user_search_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.user_search_button.clicked.connect(self.apply_user_search)
        layout.addWidget(self.user_search_button)

        return frame

    def create_advertising_search_section(self) -> QFrame:
        frame = QFrame()
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Advertising ID"))
        self.advertising_id_input = QLineEdit()
        self.advertising_id_input.setPlaceholderText("Enter advertising_id")
        self.advertising_id_input.returnPressed.connect(self.apply_advertising_search)
        layout.addWidget(self.advertising_id_input, 3)

        self.advertising_search_button = QPushButton("Search")
        self.advertising_search_button.setProperty("kind", "primary")
        self.advertising_search_button.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self.advertising_search_button.clicked.connect(self.apply_advertising_search)
        layout.addWidget(self.advertising_search_button)

        return frame

    def create_table(self) -> QFrame:
        frame = QFrame()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = DataTableView()
        self.table.setModel(self.proxy)
        self.table.selectionModel().selectionChanged.connect(self._update_status)

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
            QPushButton:disabled {
                background-color: #cbd5e1;
                color: #64748b;
            }

            QTableView {
                border: 1px solid #e2e8f0;
                border-radius: 12px;
                color: #000000;
                background-color: #ffffff;
                alternate-background-color: #f8fafc;
                gridline-color: #eff4fa;
                outline: 0;
            }
            QTableView::item { padding: 8px; border: none; }
            QTableView::item:hover { background-color: #edf4ff; }
            QTableView::item:selected {
                background-color: #0078d7;
                color: #ffffff;
            }

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
        self.user_search_button.setDisabled(is_loading)
        self.advertising_search_button.setDisabled(is_loading)
        self.mode_combo.setDisabled(is_loading)
        self.app_selector.setDisabled(is_loading)
        self.status_label.setText("Loading file..." if is_loading else "Ready")
        QApplication.setOverrideCursor(Qt.WaitCursor) if is_loading else QApplication.restoreOverrideCursor()

    def _populate_app_selector(self, df: pd.DataFrame) -> None:
        self.app_selector.clear()
        self.app_selector.addItem("All")

        if "app_id" not in df.columns:
            return

        unique_apps = df["app_id"].dropna().unique()
        self.app_selector.addItems(unique_apps)

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
            if mode == "My Chips":
                df["app_id"] = df["app_id"].astype(str).str.strip()
                df["user_id"] = df["user_id"].astype(str).str.strip()
                print("App IDs:", df["app_id"].unique()[:20])
            self.model.set_dataframe(df.reset_index(drop=True))
            self.proxy.clear_filters()
            self.user_id_input.clear()
            self.advertising_id_input.clear()
            self._populate_app_selector(df)

            self._autosize_columns()
            self._on_proxy_changed()
            self.status_label.setText(f"Loaded {len(df)} rows")

        except Exception as exc:
            self.show_error(str(exc))
        finally:
            loading.close()
            self._set_loading_state(False)

    def apply_user_search(self) -> None:
        if self.model.dataframe.empty:
            self.show_error("Please load a file first.")
            return

        user_id = self.user_id_input.text().strip()
        if not user_id:
            self.show_error("Please enter a user_id.")
            return

        selected_app = self.app_selector.currentText()
        print("Searching:", user_id, selected_app)
        print("Available user_ids:", self.model.dataframe["user_id"].unique()[:10])
        self.advertising_id_input.clear()
        self.proxy.update_user_search(user_id=user_id, app_id=selected_app)
        self._on_proxy_changed()

    def apply_advertising_search(self) -> None:
        if self.model.dataframe.empty:
            self.show_error("Please load a file first.")
            return

        if "advertising_id" not in self.model.dataframe.columns:
            self.show_error("The loaded file does not contain an 'advertising_id' column.")
            return

        advertising_id = self.advertising_id_input.text().strip()
        if not advertising_id:
            self.show_error("Please enter an advertising_id.")
            return

        self.user_id_input.clear()
        self.app_selector.setCurrentText("All")
        self.proxy.update_advertising_search(advertising_id)
        self._on_proxy_changed()

    def _autosize_columns(self) -> None:
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        for idx in range(header.count()):
            header.setSectionResizeMode(idx, QHeaderView.Interactive)
            if self.table.columnWidth(idx) > 360:
                self.table.setColumnWidth(idx, 360)

    def _filter_summary_text(self) -> str:
        if self.proxy.user_id_query:
            if self.proxy.app_id_query == "All":
                return f"user_id='{self.proxy.user_id_query}'"
            return f"user_id='{self.proxy.user_id_query}' AND app_id='{self.proxy.app_id_query}'"

        if self.proxy.advertising_id_query:
            return f"advertising_id='{self.proxy.advertising_id_query}'"

        return "none"

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
