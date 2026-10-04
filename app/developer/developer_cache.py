import json

CACHE = "developer_cache.json"


def save_cache(data):

    with open(CACHE, "w", encoding="utf-8") as f:

        json.dump(data, f, indent=4)


def load_cache():

    try:

        with open(CACHE, encoding="utf-8") as f:

            return json.load(f)

    except:

        return {}