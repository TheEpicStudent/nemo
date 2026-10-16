import inspect

from ingest import channel_replies_pull
from lib import faults, work


def formatted(fault):
    return f"{fault.name}: {fault.detail}"


def test_record_failure_stores_fault_name_with_detail():
    body = inspect.getsource(channel_replies_pull.record_failure)
    assert 'f"{fault.name}: {fault.detail}"' in body


def test_entity_fault_stored_text_starts_with_entity_prefix():
    fault = faults.fault("entity", "channel_not_found")
    assert formatted(fault)[:7] == "entity:"


def test_web_client_detail_is_not_entity_prefix_or_refusal():
    detail = (
        "The request to the Slack API failed. (url: https://slack.com/api/conversations.replies) "
        "The server responded with: {'ok': False, 'error': 'channel_not_found'}"
    )
    assert detail[:7] != "entity:"
    assert detail not in work.REFUSALS

    fault = faults.fault("entity", detail)
    assert formatted(fault)[:7] == "entity:"


def test_contended_fault_is_retryable_without_entity_prefix():
    contended_fault = faults.fault("contended", "canceling statement due to lock timeout")
    assert formatted(contended_fault)[:7] != "entity:"
    assert contended_fault.name in channel_replies_pull.RETRYABLE_FAULTS


def test_record_failure_checks_retryable_faults_by_bare_fault_name():
    body = inspect.getsource(channel_replies_pull.record_failure)
    assert "fault.name in RETRYABLE_FAULTS" in body
