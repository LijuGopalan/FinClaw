import yaml
with open('openclaw.config.yml', 'r') as f:
    config = yaml.safe_load(f)

for key, model in config['models'].items():
    model['provider'] = 'google'
    model['model_id'] = 'gemini-3.1-pro-preview'
    model['api_key_env'] = 'GOOGLE_API_KEY'

with open('openclaw.config.yml', 'w') as f:
    yaml.dump(config, f, sort_keys=False)
