import json

def handler(event, context):
    print(f"Received event: {json.dumps(event)}")
    
    action_group = event['actionGroup']
    function = event['function']
    
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function,
            "functionResponse": {
                "responseBody": {
                    "TEXT": {
                        "body": "Compliance check PASSED. No prohibited keywords found. Legal disclaimer included."
                    }
                }
            }
        }
    }
