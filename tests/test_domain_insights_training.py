import json

import pytest

from backend.app.analytics import improvements
from backend.app.core.registry import DuplicateRegistration
from backend.app.domain import training_defs as td
from backend.app.domain.insights import Insight, from_corner_item, from_corner_report, from_improvement, from_improvements
from backend.app.domain.timing_models import SECTORS_NOTE, LapTime, best_lap
from backend.app.spatial_coaching import corner_report


def test_insight_from_real_improvements_output():
    laps = [{'number': n, 'overlap_s': 3, 'coast_s': 0, 'limiter_s': 0} for n in (1, 2, 3)]
    cards = improvements(laps)
    [insight] = from_improvements(cards)
    assert isinstance(insight, Insight) and insight.id == 'improvement:overlap_s' and insight.lap == 3
    assert insight.metric == {'name': 'affected_laps', 'value': 3, 'unit': 'laps'}
    assert insight.evidence['laps'] == [1, 2, 3] and insight.suggested_followup == cards[0]['advice']
    assert insight.description == cards[0]['observation'] and insight.severity == 'notice'
    json.dumps(insight.to_public())


def test_insight_from_corner_report_item_shape():
    item = {'id': 'corner:T3', 'priority': 2, 'kind': 'corner_loss', 'corner': 'Turn 3', 'lap': 5, 'loss_s': 0.42,
            'causes': [('onset', -12.0), ('min_speed', -4.0)], 'confidence': 'moderate', 'text': 'Turn 3: 0.4 s slower'}
    insight = from_corner_item(item)
    assert insight.corner_id == 'T3' and insight.lap == 5 and insight.severity == 'notice'
    assert insight.metric == {'name': 'loss_s', 'value': 0.42, 'unit': 's'} and insight.comparison['delta_s'] == 0.42
    assert insight.evidence['causes'] == [{'kind': 'onset', 'value': -12.0}, {'kind': 'min_speed', 'value': -4.0}]
    gain = from_corner_item({**item, 'loss_s': -0.3, 'priority': 3})
    assert gain.severity == 'info'
    assert [i.id for i in from_corner_report([item])] == ['corner:T3']
    assert corner_report is not None                                     # producer imported: shapes above are its real keys


def test_timing_models():
    laps = [{'number': 1, 'duration_ms': 91000, 'comparable': True, 'timing_source': 'game'},
            {'number': 2, 'duration_ms': 89000, 'comparable': False},
            {'number': 3, 'duration_ms': None, 'comparable': True}]
    times = [LapTime.from_lap(l) for l in laps]
    assert times[0].seconds == 91.0 and times[2].seconds is None and times[1].source == 'unknown'
    assert best_lap(times).lap == 1 and best_lap([]) is None
    assert 'not transmitted' in SECTORS_NOTE


def lap(n, ms, clean=True):
    return {'number': n, 'duration_ms': ms, 'complete': clean, 'comparable': clean}


def test_three_example_achievements_are_pure_evaluators():
    assert {'first_clean_lap', 'five_consistent_laps', 'first_completed_session'} <= set(td.ACHIEVEMENTS.ids())
    empty = {'status': 'driving', 'provenance': 'live', 'laps': []}
    assert not any(p.met for p in td.evaluate_all(empty).values())

    one = {'status': 'driving', 'provenance': 'live', 'laps': [lap(1, 95000, False), lap(2, 91000)]}
    assert td.evaluate(td.ACHIEVEMENTS.require('first_clean_lap'), one).met
    assert td.evaluate(td.ACHIEVEMENTS.require('first_clean_lap'), one).evidence == {'laps': [2]}

    steady = {'status': 'driving', 'provenance': 'live', 'laps': [lap(i, 90000 + d) for i, d in enumerate((0, 400, -300, 200, 100), 1)]}
    assert td.evaluate(td.ACHIEVEMENTS.require('five_consistent_laps'), steady).met
    loose = {'laps': [lap(1, 90000), lap(2, 95000), lap(3, 90100), lap(4, 89900), lap(5, 90050)]}
    progress = td.evaluate(td.ACHIEVEMENTS.require('five_consistent_laps'), loose)
    assert not progress.met and progress.current == 3 and progress.target == 5     # the 95 s lap breaks the run
    broken = {'laps': [lap(1, 90000), lap(2, 90000), lap(3, 90000, False), lap(4, 90000), lap(5, 90000)]}
    assert td.evaluate(td.ACHIEVEMENTS.require('five_consistent_laps'), broken).current == 2

    done = {'status': 'completed', 'provenance': 'live', 'laps': [lap(1, 90000)]}
    assert td.evaluate(td.ACHIEVEMENTS.require('first_completed_session'), done).met
    for bad in ({**done, 'provenance': 'demo'}, {**done, 'status': 'interrupted'}, {**done, 'laps': []}):
        assert not td.evaluate(td.ACHIEVEMENTS.require('first_completed_session'), bad).met
    assert td.evaluate(td.CHALLENGES.require('clean_stint_10'), {'laps': [lap(i, 90000) for i in range(10)]}).met


def test_evaluators_do_not_mutate_input_and_registry_is_strict():
    summary = {'status': 'completed', 'provenance': 'live', 'laps': [lap(1, 90000)]}
    before = json.dumps(summary, sort_keys=True)
    td.evaluate_all(summary)
    assert json.dumps(summary, sort_keys=True) == before
    with pytest.raises(DuplicateRegistration):
        td.ACHIEVEMENTS.register(td.ACHIEVEMENTS.require('first_clean_lap'))
    assert all(p['evaluator'] in td.EVALUATORS for p in td.ACHIEVEMENTS.to_public())
    json.dumps(td.ACHIEVEMENTS.to_public() + td.CHALLENGES.to_public() + td.EVALUATORS.to_public())
    assert td.evaluate_all(summary, td.CHALLENGES)['clean_stint_10'].to_public()['met'] is False
