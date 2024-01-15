import json
import re
import time
from json import JSONDecodeError
from typing import Any, Optional, Sequence

from anki.collection import Collection
from anki.notes import NoteId
from aqt import gui_hooks
from aqt.browser.browser import Browser
from aqt.operations import QueryOp
from aqt.qt import (  # type: ignore
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QIntValidator,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRegularExpression,
    QRegularExpressionValidator,
    QVBoxLayout,
)
from aqt.utils import qconnect, showCritical, showWarning, tooltip

from .common import CONFIG_VERSION, Config, load_config, mw, show_update_nag
from .openai import OpenAIConnection


class ConsultDialog(QDialog):  # type: ignore
    def __init__(
        self,
        config: Config,
        common_field_names: list[str],
    ):
        super().__init__()
        self.setWindowTitle("Consult the Soothsayer")
        self.resize(400, 400)

        layout = QVBoxLayout(self)
        self.setLayout(layout)

        question_label = QLabel("Question")
        question_label.setToolTip(
            "Question to ask ChatGPT. Text in curly braces is substituted with card content; e.g., {Word}."
        )
        self.question_text_edit = QPlainTextEdit()
        self.question_text_edit.setPlainText(config.question)

        request_options_label = QLabel("Request Options")
        request_options_label.setToolTip(
            "Options to pass along with the API request. See the official OpenAI API documentation."
        )
        self.request_options_text_edit = QPlainTextEdit()
        self.request_options_text_edit.setPlainText(config.request_options)

        self.answer_field_combo_box = QComboBox()
        self.answer_field_combo_box.addItems(common_field_names)
        try:
            index = common_field_names.index(config.answer_field)
        except ValueError:
            index = 0
        self.answer_field_combo_box.setCurrentIndex(index)

        self.tag_line_edit = QLineEdit()
        self.tag_line_edit.setText(config.tag)
        self.tag_line_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(r"[^\s,]*"))
        )

        self.openai_api_key_line_edit = QLineEdit()
        self.openai_api_key_line_edit.setText(config.openai_api_key)
        self.openai_api_key_line_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self.timeout_line_edit = QLineEdit()
        self.timeout_line_edit.setText(str(config.timeout))
        self.timeout_line_edit.setValidator(QIntValidator(1, 2**31 - 1))

        self.max_retries_line_edit = QLineEdit()
        self.max_retries_line_edit.setText(str(config.max_retries))
        self.max_retries_line_edit.setValidator(QIntValidator(1, 2**31 - 1))

        grid = QGridLayout()
        grid.addWidget(question_label, 0, 0)
        grid.addWidget(self.question_text_edit, 1, 0, 1, 2)
        for i, (label_text, label_tooltip, control) in enumerate(
            [
                (
                    "Answer Field",
                    "Field which will be set to the answer provided by ChatGPT.",
                    self.answer_field_combo_box,
                ),
                (
                    "Tag",
                    "Optional tag to add to notes in addition to the answer provided by ChatGPT.",
                    self.tag_line_edit,
                ),
                (
                    "OpenAI API Key",
                    "Secret personal OpenAI API key.",
                    self.openai_api_key_line_edit,
                ),
                (
                    "Timeout (Seconds)",
                    "Timeout in seconds before failing an HTTP request.",
                    self.timeout_line_edit,
                ),
                (
                    "Max Retries",
                    "Maximum number of times to retry an HTTP request before giving up.",
                    self.max_retries_line_edit,
                ),
            ]
        ):
            label = QLabel(label_text)
            label.setToolTip(label_tooltip)
            grid.addWidget(label, 2 + i, 0)
            grid.addWidget(control, 2 + i, 1)
        grid.addWidget(request_options_label, 2 + i + 1, 0)
        grid.addWidget(self.request_options_text_edit, 2 + i + 2, 0, 1, 2)

        layout.addLayout(grid)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        apply_button = button_box.button(QDialogButtonBox.StandardButton.Apply)
        apply_button.setAutoDefault(True)
        apply_button.setDefault(True)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_button.setAutoDefault(False)
        cancel_button.setDefault(False)

        layout.addWidget(button_box)
        qconnect(apply_button.clicked, self.accept)
        qconnect(button_box.accepted, self.accept)
        qconnect(button_box.rejected, self.reject)

    def get_config(self) -> Config:
        return Config(
            answer_field=self.answer_field_combo_box.currentText(),
            config_version=CONFIG_VERSION,
            max_retries=int(self.max_retries_line_edit.text()),
            openai_api_key=self.openai_api_key_line_edit.text(),
            question=self.question_text_edit.toPlainText(),
            request_options=self.request_options_text_edit.toPlainText(),
            tag=self.tag_line_edit.text(),
            timeout=int(self.timeout_line_edit.text()),
        )


def show_consult_dialog(
    config: Config,
    common_field_names: list[str],
) -> Optional[Config]:
    dialog = ConsultDialog(config, common_field_names)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        return dialog.get_config()
    return None


# adapted from https://github.com/DillonWall/generate-batch-audio-anki-addon
def replace_fields(s: str, replacements: dict[str, str]) -> str:
    val_str = ""
    for sub_str in re.split("({[^}]*})", s):
        if sub_str.startswith("{"):
            val_str += sub_str.lower()
        else:
            val_str += sub_str

    for key, value in replacements.items():
        val_str = val_str.replace("{" + key.lower() + "}", value)

    return val_str


def update_note(
    col: Collection,
    config: Config,
    openai: OpenAIConnection,
    request_options: dict[str, Any],
    nid: NoteId,
) -> None:
    note = col.get_note(nid)
    replacements = {k.lower(): v for k, v in note.items()}
    query = replace_fields(config.question, replacements)
    note[config.answer_field] = openai.ask(query, request_options)
    note.add_tag(config.tag)
    col.update_note(note)


def update_notes(
    browser: Browser,
    config: Config,
    request_options: dict[str, Any],
    nids: Sequence[NoteId],
) -> None:
    total_nids = len(nids)

    # The checkpoint system (mw.checkpoint() and mw.reset()) are "obsoleted" in favor of
    # Collection Operations. However, Collection Operations have a very short-term
    # memory (~30), which is unsuitable for the potentially massive amounts of changes
    # that Hanzi Web will do on a collection.
    #
    # https://addon-docs.ankiweb.net/background-ops.html?highlight=undo#collection-operations
    mw.checkpoint("Consult the Soothsayer")
    browser.begin_reset()
    mw.progress.finish()
    mw.progress.start(parent=browser, label="Consulting the Soothsayer...")

    openai = OpenAIConnection(
        api_key=config.openai_api_key,
        timeout=config.timeout,
        max_retries=config.max_retries,
    )

    def do_op(col: Collection) -> None:
        last_progress = 0.0
        for i, nid in enumerate(nids):
            if time.time() - last_progress >= 0.1:
                mw.taskman.run_on_main(
                    lambda: mw.progress.update(
                        label=f"Consulting the Soothsayer: {i}/{total_nids}",
                        value=i,
                        max=total_nids,
                    )
                )
                last_progress = time.time()
            if mw.progress.want_cancel():
                break
            last_progress = time.time()
            update_note(col, config, openai, request_options, nid)

    def do_finally() -> None:
        openai.close()
        mw.progress.finish()
        browser.end_reset()
        mw.reset()

    def do_failure(exception: Exception) -> None:
        do_finally()
        showWarning(str(exception), parent=browser)

    # HACK: Use QueryOp and bypass poorly documented CollectionOp nonsense.
    QueryOp(
        parent=browser,
        op=do_op,
        success=lambda result: do_finally(),
    ).failure(do_failure).run_in_background()


def maybe_ask(browser: Browser) -> None:
    config = load_config()
    if config.config_version < CONFIG_VERSION:
        show_update_nag()
        return
    nids = browser.selected_notes()
    if not nids:
        tooltip("No notes selected.", parent=browser)
        return
    new_config = show_consult_dialog(
        config,
        list(sorted(mw.col.field_names_for_note_ids(nids))),
    )
    if not new_config:
        return
    new_config.write()

    if new_config.request_options:
        try:
            request_options = json.loads(new_config.request_options)
        except JSONDecodeError:
            showCritical(
                "The given extra request options are not properly formatted JSON.",
                parent=browser,
            )
            return
    else:
        request_options = {}

    update_notes(browser, new_config, request_options, nids)


def init(browser: Browser) -> None:
    ask_action = browser.form.menuEdit.addAction("Consult the &Soothsayer...")
    qconnect(ask_action.triggered, lambda: maybe_ask(browser))


gui_hooks.browser_menus_did_init.append(init)
