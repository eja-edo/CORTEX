import httpx, json

BASE = 'http://localhost:8000/api'

# Login
r = httpx.post(f'{BASE}/auth/token', json={'username': 'test@example.com', 'password': 'test'})
if r.status_code != 200:
    print('Login failed:', r.status_code, r.text[:200])
    exit()
token = r.json()['access_token']
print('Token OK')

headers = {'Authorization': f'Bearer {token}'}

# List workflows
r = httpx.get(f'{BASE}/v1/workflows', headers=headers)
print(f'List workflows: {r.status_code}')
if r.status_code == 200:
    data = r.json()
    print(f'  Found {data["total"]} workflows')
    for wf in data.get('items', []):
        print(f'  - {wf["id"]} {wf["name"]} trigger={wf["trigger_type"]} status={wf["status"]}')

# If we have a schedule workflow, try executing a notification node
for wf in data.get('items', []):
    if wf['trigger_type'] == 'schedule':
        wf_id = wf['id']
        print(f'\nUsing workflow: {wf_id} {wf["name"]}')
        definition = wf.get('definition', {})
        nodes = definition.get('nodes', [])
        for node in nodes:
            ntype = node.get('type', '')
            if 'notification' in ntype or 'send' in ntype:
                node_id = node['id']
                config = node.get('data', {}).get('config', {})
                print(f'  Notification node: {node_id}')
                print(f'  Config: {json.dumps(config, indent=2)}')
                
                # Execute with empty trigger_data
                r2 = httpx.post(
                    f'{BASE}/v1/workflows/{wf_id}/nodes/{node_id}/execute',
                    headers=headers,
                    json={'config': config, 'trigger_data': {}, 'previous_outputs': {}}
                )
                print(f'  Execute result: {r2.status_code}')
                if r2.status_code == 200:
                    print(f'  Response: {json.dumps(r2.json(), indent=2)}')
                break
        break
