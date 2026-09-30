import pytest
from backend.app.gamification.scoring import score_to_grade, evaluate
from backend.app.gamification.mastery import components_score

def test_score_to_grade_mapping():
    assert score_to_grade(98.0) == 'S'
    assert score_to_grade(95.0) == 'S'
    assert score_to_grade(90.0) == 'A'
    assert score_to_grade(75.0) == 'B'
    assert score_to_grade(60.0) == 'C'
    assert score_to_grade(40.0) == 'D'
    assert score_to_grade(None) is None

def test_evaluate_includes_session_grade():
    session = {'provenance': 'live', 'ended': True, 'status': 'completed', 'id': 'sess_1',
               'laps': [{'id': 'l1', 'comparable': True, 'complete': True, 'partial': False, 'quality': [], 'refuel': False, 'duration_ms': 90000},
                        {'id': 'l2', 'comparable': True, 'complete': True, 'partial': False, 'quality': [], 'refuel': False, 'duration_ms': 90500}]}
    context = {'integrity': True, 'laps': {'l1': {'car_id': 1, 'layout_id': 'spa', 'provenance': 'live', 'identity_state': 'authoritative', 'integrity': True},
                                           'l2': {'car_id': 1, 'layout_id': 'spa', 'provenance': 'live', 'identity_state': 'authoritative', 'integrity': True}}}
    res = evaluate(session, context)
    assert res['status'] == 'eligible'
    assert res['evidence']['session_grade'] in ('S', 'A', 'B', 'C', 'D')

def test_components_score_calculation():
    comp = {'pace': 80.0, 'consistency': 90.0, 'corners': 85.0, 'training': 70.0, 'strategy': 75.0}
    res = components_score(comp)
    assert res['overall_score'] is not None
    assert 0 <= res['overall_score'] <= 100
    assert res['component_coverage'] == 1.0
