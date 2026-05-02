from __future__ import annotations


def _gpt_payload():
    return {
        "track_type": "circle",
        "start_point": {"x": 0, "y": 0},
        "altitude_m": 5.0,
        "wind": {"north": 0, "east": 0, "south": 0, "west": 0},
        "sensor_noise_level": "medium",
        "objective_profile": "robust",
        "optimizer_strategy": "gpt",
        "simulator_backend": "mock",
        "openai": {"model": "gpt-4o-mini"},
    }


def _create_job(client, payload):
    resp = client.post('/api/v1/jobs', json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()['data']['id']


def test_gpt_without_key_fails_when_hosted_server_key_disabled(client):
    resp = client.post('/api/v1/jobs', json=_gpt_payload())
    assert resp.status_code == 422


def test_gpt_without_key_succeeds_when_hosted_server_key_enabled(client, monkeypatch):
    monkeypatch.setenv('HOSTED_ALLOW_SERVER_OPENAI_KEY', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-server-key')
    monkeypatch.setenv('APP_SECRET_KEY', 'dev-secret')
    from app.config import get_settings
    get_settings.cache_clear()
    resp = client.post('/api/v1/jobs', json=_gpt_payload())
    assert resp.status_code == 200, resp.text


def test_non_gpt_unaffected(client):
    payload = _gpt_payload()
    payload['optimizer_strategy'] = 'heuristic'
    payload.pop('openai', None)
    resp = client.post('/api/v1/jobs', json=payload)
    assert resp.status_code == 200


def test_non_gpt_does_not_set_openai_model_when_env_is_configured(client, monkeypatch):
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-4o-mini')
    from app.config import get_settings
    get_settings.cache_clear()
    payload = _gpt_payload()
    payload['optimizer_strategy'] = 'heuristic'
    payload.pop('openai', None)
    resp = client.post('/api/v1/jobs', json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()['data']['openai_model'] is None


def test_gpt_explicit_key_still_works(client, monkeypatch):
    monkeypatch.setenv('APP_SECRET_KEY', 'dev-secret')
    from app.config import get_settings
    get_settings.cache_clear()
    payload = _gpt_payload()
    payload['openai']['api_key'] = 'sk-user'
    resp = client.post('/api/v1/jobs', json=payload)
    assert resp.status_code == 200, resp.text


def test_gpt_uses_openai_model_env_when_request_model_missing_with_explicit_key(client, monkeypatch):
    monkeypatch.setenv('APP_SECRET_KEY', 'dev-secret')
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-4o-mini')
    from app.config import get_settings
    get_settings.cache_clear()
    payload = _gpt_payload()
    payload['openai'] = {'api_key': 'sk-user'}
    resp = client.post('/api/v1/jobs', json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()['data']['openai_model'] == 'gpt-4o-mini'


def test_gpt_uses_openai_model_env_when_request_model_missing_with_server_key_mode(client, monkeypatch):
    monkeypatch.setenv('HOSTED_ALLOW_SERVER_OPENAI_KEY', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-server-key')
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-4o-mini')
    monkeypatch.setenv('APP_SECRET_KEY', 'dev-secret')
    from app.config import get_settings
    get_settings.cache_clear()
    payload = _gpt_payload()
    payload['openai'] = {}
    resp = client.post('/api/v1/jobs', json=payload)
    assert resp.status_code == 200, resp.text
    assert resp.json()['data']['openai_model'] == 'gpt-4o-mini'


def test_rerun_gpt_without_key_fails_when_server_mode_disabled(client, monkeypatch):
    monkeypatch.setenv('APP_SECRET_KEY', 'dev-secret')
    from app.config import get_settings
    get_settings.cache_clear()
    payload = _gpt_payload(); payload['openai']['api_key'] = 'sk-user'
    job_id = _create_job(client, payload)
    resp = client.post(f'/api/v1/jobs/{job_id}/rerun', json={})
    assert resp.status_code == 422


def test_rerun_gpt_without_key_succeeds_when_server_mode_enabled(client, monkeypatch):
    monkeypatch.setenv('HOSTED_ALLOW_SERVER_OPENAI_KEY', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-server-key')
    monkeypatch.setenv('APP_SECRET_KEY', 'dev-secret')
    from app.config import get_settings
    get_settings.cache_clear()
    payload = _gpt_payload(); payload['openai']['api_key'] = 'sk-user'
    job_id = _create_job(client, payload)
    resp = client.post(f'/api/v1/jobs/{job_id}/rerun', json={})
    assert resp.status_code == 200, resp.text


def test_rerun_gpt_with_explicit_key_fails_when_secret_store_not_configured(client, monkeypatch):
    monkeypatch.setenv('APP_SECRET_KEY', 'dev-secret')
    from app.config import get_settings
    get_settings.cache_clear()
    payload = _gpt_payload(); payload['openai']['api_key'] = 'sk-user'
    job_id = _create_job(client, payload)
    monkeypatch.delenv('APP_SECRET_KEY', raising=False)
    monkeypatch.delenv('DRONEDREAM_SECRET_KEY', raising=False)
    get_settings.cache_clear()
    resp = client.post(
        f'/api/v1/jobs/{job_id}/rerun',
        json={'openai': {'api_key': 'sk-rerun'}},
    )
    assert resp.status_code == 500, resp.text
    assert resp.json()['error']['code'] == 'CONFIGURATION_ERROR'


def test_rerun_gpt_with_server_key_mode_fails_when_secret_store_not_configured(client, monkeypatch):
    monkeypatch.setenv('HOSTED_ALLOW_SERVER_OPENAI_KEY', 'true')
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-server-key')
    monkeypatch.setenv('APP_SECRET_KEY', 'dev-secret')
    from app.config import get_settings
    get_settings.cache_clear()
    payload = _gpt_payload(); payload['openai']['api_key'] = 'sk-user'
    job_id = _create_job(client, payload)
    monkeypatch.delenv('APP_SECRET_KEY', raising=False)
    monkeypatch.delenv('DRONEDREAM_SECRET_KEY', raising=False)
    get_settings.cache_clear()
    resp = client.post(f'/api/v1/jobs/{job_id}/rerun', json={})
    assert resp.status_code == 500, resp.text
    assert resp.json()['error']['code'] == 'CONFIGURATION_ERROR'


def test_rerun_non_gpt_unaffected(client):
    payload = _gpt_payload(); payload['optimizer_strategy'] = 'heuristic'; payload.pop('openai', None)
    job_id = _create_job(client, payload)
    resp = client.post(f'/api/v1/jobs/{job_id}/rerun', json={})
    assert resp.status_code == 200, resp.text
