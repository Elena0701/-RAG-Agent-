"""Controlled test-only login; no API calls or production invitation files."""
def login_as(app, client, role="admin", name="CONTROLLED test account", **limits):
    record=app.extensions['access_control'].create_invite(name,role=role,**limits)
    token=client.get('/api/bootstrap').get_json()['review_token']
    response=client.post('/api/auth/login',json={'code':record['code']},headers={'X-Workbench-Token':token})
    assert response.status_code==200
    return record,{'X-Workbench-Token':token}
