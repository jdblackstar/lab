import pytest
import verifiers as vf
from xmage_poc.environment import completion_action


@pytest.mark.parametrize(
    "content",
    [
        ' {"action": 7} \n',
        '```json\n{"action": 7}\n```',
        '```\n{"action": 7}\n```',
        '<answer>{"action": 7}</answer>',
        'Consider {"action": 2}, but choose 7.\n<answer>{"action": 7}</answer>',
        '<think>Consider action 2.</think>\n<answer>```json\n{"action": 7}\n```</answer>',
    ],
)
def test_only_the_committed_answer_selects_an_action(content):
    assert completion_action([vf.AssistantMessage(content=content)]) == 7


def test_hidden_reasoning_and_multipart_visible_content_are_independent():
    message = vf.AssistantMessage(
        content=[
            {"type": "text", "text": 'Consider {"action": 2}.\n<answer>'},
            {"type": "text", "text": '{"action": 7}</answer>'},
        ],
        reasoning_content='I considered {"action": 3}.',
    )
    assert completion_action([message]) == 7
    assert (
        completion_action(
            [vf.AssistantMessage(content='{"action": 7}', reasoning_content="Think")]
        )
        == 7
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        None,
        '{"action": true}',
        '{"action": 7.0}',
        '{"action": "7"}',
        '{"action": 7, "reason": "attack"}',
        '{"action": 2, "action": 7}',
        '[{"action": 7}]',
        '[["action", 7]]',
        '{"action": 2}\n{"action": 7}',
        'Choose this: {"action": 7}',
        '<answer>{"action": 2}</answer><answer>{"action": 7}</answer>',
        '<answer><answer>{"action": 7}</answer></answer>',
        '<answer>{"action": 7}',
        '<answer>{"action": 7}</answer> Actually, choose 2.',
        '<answer>{"action": 7}</answer><answer>',
        '<answer>{"action": 7, "action": 2}</answer>',
        '```json\n{"action": 7}',
        '```json\n{"action": 2}\n```\n```json\n{"action": 7}\n```',
    ],
)
def test_invalid_or_ambiguous_answers_still_raise_model_response_error(content):
    with pytest.raises(vf.InvalidModelResponseError):
        completion_action([vf.AssistantMessage(content=content)])


def test_never_fall_back_to_an_earlier_turns_answer():
    with pytest.raises(vf.InvalidModelResponseError):
        completion_action(
            [
                vf.AssistantMessage(content='<answer>{"action": 2}</answer>'),
                vf.AssistantMessage(content='<answer>{"action": 7}'),
            ]
        )
