from pathlib import Path

ROUTER = Path('app/equalizador/router.py').read_text(encoding='utf-8')


def test_phase63_checkbox_and_file_inputs_not_full_width():
    assert 'input[type="checkbox"], input[type="radio"]' in ROUTER
    assert 'width: auto' in ROUTER
    assert 'input[type="file"]::file-selector-button' in ROUTER


def test_phase63_bulk_actions_hidden_when_idle_and_non_overlapping():
    assert '.bulk-actions.idle .toolbar { display: none; }' in ROUTER
    assert '.bulk-actions.active' in ROUTER
    assert 'bulkBox.classList.toggle("idle", selected.length === 0)' in ROUTER
    assert 'position: static; margin-top: 10px' in ROUTER


def test_phase63_feedback_copy_per_item_and_dedup():
    assert 'feedback-copy-one' in ROUTER
    assert 'copyText = async' in ROUTER
    assert 'previous && previous.kind === level && previous.text === clean' in ROUTER
    assert 'feedbackEntries = feedbackEntries.filter' in ROUTER


def test_phase63_focus_scroll_for_android_keyboard():
    assert 'focusin' in ROUTER
    assert 'scrollIntoView({ block: "center", behavior: "smooth" })' in ROUTER
    assert 'scroll-margin-bottom: 320px' in ROUTER
