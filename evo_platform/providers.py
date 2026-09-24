"""OpenAI-compatible judge used by both RAG and application evaluation."""
def openai_judge(model_name, api_key):
    from deepeval.models import DeepEvalBaseLLM
    from openai import OpenAI
    import asyncio
    import json

    class Judge(DeepEvalBaseLLM):
        def __init__(self):
            self.model_name = model_name
            self.client = OpenAI(api_key=api_key, timeout=120, max_retries=0)

        def load_model(self):
            return self.client

        def get_model_name(self):
            return self.model_name

        def generate(self, prompt, schema=None):
            options = {'response_format': {'type': 'json_object'}} if schema else {}
            response = self.client.chat.completions.create(model=self.model_name, messages=[{'role': 'user', 'content': prompt}], **options)
            content = response.choices[0].message.content or ''
            return schema(**json.loads(content)) if schema else content

        async def a_generate(self, prompt, schema=None):
            return await asyncio.to_thread(self.generate, prompt, schema)

    return Judge()
