import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

import pandas as pd
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass
class ExcelData:
    """Loader for Company 1 Excel files."""

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
        df["payout"] = pd.to_numeric(df["payout"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        self.dataframe = df
        return df


@dataclass
class PostbackData:
    """Loader for Company 2 CSV files with postback parsing."""

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

        return {
            "user_id": self._extract_user_id(raw_user),
            "payout": pd.to_numeric(payout, errors="coerce"),
            "reward": pd.to_numeric(reward, errors="coerce"),
            "offer_name": unquote(offer_name),
            "task_name": unquote(task_name),
            "status": unquote(status),
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Local Data Analysis Tool")
        self.resize(1200, 750)

        self.excel_data = ExcelData()
        self.postback_data = PostbackData()

        self.original_df = pd.DataFrame()
        self.current_df = pd.DataFrame()

        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        top_layout = QHBoxLayout()
        top_layout.setSpacing(10)

        self.mode_label = QLabel("Mode")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Company 1", "Company 2"])

        self.load_button = QPushButton("Load File")
        self.load_button.clicked.connect(self.load_file)

        top_layout.addWidget(self.mode_label)
        top_layout.addWidget(self.mode_combo)
        top_layout.addStretch()
        top_layout.addWidget(self.load_button)

        search_layout = QHBoxLayout()
        search_layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by user_id (exact match)")
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.search_by_user_id)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_data)

        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_button)
        search_layout.addWidget(self.reset_button)

        sort_layout = QHBoxLayout()
        sort_layout.setSpacing(10)

        self.payout_sort_combo = QComboBox()
        self.payout_sort_combo.addItems([
            "Sort payout: None",
            "Sort payout: High → Low",
            "Sort payout: Low → High",
        ])
        self.payout_sort_combo.currentIndexChanged.connect(self.apply_sorts)

        self.date_sort_combo = QComboBox()
        self.date_sort_combo.addItems([
            "Sort date: None",
            "Sort date: Newest → Oldest",
            "Sort date: Oldest → Newest",
        ])
        self.date_sort_combo.currentIndexChanged.connect(self.apply_sorts)

        self.alpha_sort_combo = QComboBox()
        self.alpha_sort_combo.addItems([
            "Sort A-Z: None",
            "Sort A-Z",
            "Sort Z-A",
        ])
        self.alpha_sort_combo.currentIndexChanged.connect(self.apply_sorts)

        sort_layout.addWidget(self.payout_sort_combo)
        sort_layout.addWidget(self.date_sort_combo)
        sort_layout.addWidget(self.alpha_sort_combo)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)

        root.addLayout(top_layout)
        root.addLayout(search_layout)
        root.addLayout(sort_layout)
        root.addWidget(self.table)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background-color: #f7f8fa; }
            QLabel { font-size: 13px; color: #2f3542; }
            QLineEdit, QComboBox {
                background: white;
                border: 1px solid #dfe4ea;
                border-radius: 8px;
                padding: 6px 8px;
                min-height: 30px;
            }
            QPushButton {
                background-color: #2f80ed;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 8px 14px;
                min-height: 30px;
            }
            QPushButton:hover { background-color: #1f6fd6; }
            QTableWidget {
                background: white;
                border: 1px solid #dfe4ea;
                border-radius: 8px;
                gridline-color: #ecf0f1;
                font-size: 12px;
            }
            """
        )

    def show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def load_file(self) -> None:
        mode = self.mode_combo.currentText()

        if mode == "Company 1":
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

        try:
            if mode == "Company 1":
                df = self.excel_data.load(file_path)
            else:
                df = self.postback_data.load(file_path)

            self.original_df = df.copy()
            self.current_df = df.copy()
            self._reset_sort_controls()
            self.update_table(self.current_df)

        except Exception as exc:
            self.show_error(str(exc))

    def search_by_user_id(self) -> None:
        if self.original_df.empty:
            self.show_error("Please load a file first.")
            return

        query = self.search_input.text().strip()
        if not query:
            self.current_df = self.original_df.copy()
            self.apply_sorts()
            return

        filtered = self.original_df[
            self.original_df["user_id"].astype(str).str.strip() == query
        ].copy()
        self.current_df = filtered
        self.apply_sorts()

    def reset_data(self) -> None:
        if self.original_df.empty:
            return
        self.search_input.clear()
        self.current_df = self.original_df.copy()
        self._reset_sort_controls()
        self.update_table(self.current_df)

    def _reset_sort_controls(self) -> None:
        self.payout_sort_combo.setCurrentIndex(0)
        self.date_sort_combo.setCurrentIndex(0)
        self.alpha_sort_combo.setCurrentIndex(0)

    def apply_sorts(self) -> None:
        if self.current_df.empty:
            self.update_table(self.current_df)
            return

        df = self.current_df.copy()

        payout_idx = self.payout_sort_combo.currentIndex()
        if payout_idx and "payout" in df.columns:
            df["payout"] = pd.to_numeric(df["payout"], errors="coerce")
            df = df.sort_values("payout", ascending=(payout_idx == 2), na_position="last")

        date_idx = self.date_sort_combo.currentIndex()
        if date_idx and "date" in df.columns:
            date_values = pd.to_datetime(df["date"], errors="coerce")
            df = df.assign(__date_temp=date_values).sort_values(
                "__date_temp", ascending=(date_idx == 2), na_position="last"
            )
            df = df.drop(columns=["__date_temp"])

        alpha_idx = self.alpha_sort_combo.currentIndex()
        if alpha_idx:
            alpha_col = self._best_alpha_column(df)
            if alpha_col:
                df = df.sort_values(
                    by=alpha_col,
                    ascending=(alpha_idx == 1),
                    key=lambda s: s.astype(str).str.lower(),
                    na_position="last",
                )

        self.current_df = df
        self.update_table(self.current_df)

    def _best_alpha_column(self, df: pd.DataFrame) -> Optional[str]:
        for candidate in ["app", "offer_name", "task_name", "status", "user_id"]:
            if candidate in df.columns:
                return candidate
        return None

    def update_table(self, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        display_df = df.reset_index(drop=True)
        columns = list(display_df.columns)

        self.table.clear()
        self.table.setRowCount(len(display_df))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        for row_idx in range(len(display_df)):
            for col_idx, column in enumerate(columns):
                value = display_df.iat[row_idx, col_idx]
                text = "" if pd.isna(value) else str(value)
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                self.table.setItem(row_idx, col_idx, item)

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
