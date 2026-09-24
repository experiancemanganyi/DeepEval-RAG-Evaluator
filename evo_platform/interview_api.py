"""Adapter for the existing AI Interview public practice API. Never edits server data/config."""
import json
from .connectors import APIConnector, ConnectorError
from .store import normalize


class InterviewAPIConnector(APIConnector):
    def options(self, domain_id=None):
        path = '/api/config-options'
        if domain_id is not None:
            path += '?domain_id=' + str(int(domain_id))
        data = self.request('GET', path)
        if not isinstance(data, dict) or not isinstance(data.get('domains'), list):
            raise ConnectorError('Interview configuration response is not supported')
        return data

    def discover_capabilities(self):
        self.options()  # A real read-only connection check.
        return {'catalog': True, 'technology_discovery': True, 'question_selection': True,
                'complete_coverage': False, 'transport': 'Interview practice API'}

    def technologies(self):
        data = self.options(self.config.get('domain_id'))
        return [{'id': str(t['TechnologyID']), 'name': t['TechnologyName']} for t in data['technologies']]

    def session_questions(self, technology_id):
        body = {'practice_type': self.config.get('practice_type', 'Technical'),
                'domain_id': int(self.config['domain_id']), 'technology_ids': [int(technology_id)],
                'level_rank': int(self.config.get('level_rank', 2))}
        data = self.request('POST', '/api/start-session', json=body)
        questions = data.get('questions') if isinstance(data, dict) else None
        if not isinstance(questions, list) or any(not isinstance(q, dict) or
                not isinstance(q.get('QuestionText'), str) or not q.get('QuestionID') for q in questions):
            raise ConnectorError('Interview session returned an invalid question list')
        return questions

    def catalog(self):
        selected = {str(t) for t in self.config.get('technology_ids', [])}
        if not selected:
            raise ConnectorError('Choose at least one interview technology')
        technologies = {t['id']: t['name'] for t in self.technologies()}
        if not selected <= technologies.keys():
            raise ConnectorError('Selected technology is no longer in this domain')
        records = []
        for technology in sorted(selected):
            for q in self.session_questions(technology):
                records.append({'technology': technologies[technology], 'technology_id': technology,
                                'question_id': str(q['QuestionID']), 'question': q['QuestionText']})
        # start-session supplies a session sample, not authoritative catalog totals.
        return records, None

    def start_session(self, snapshot):
        technology = str(snapshot['technology_external_id'])
        if technology not in {str(t) for t in self.config.get('technology_ids', [])}:
            raise ConnectorError('Case technology is not selected in the saved interview connection')
        matches = [q for q in self.session_questions(technology)
                   if str(q['QuestionID']) == str(snapshot['external_id'])]
        if len(matches) != 1 or normalize(matches[0]['QuestionText']) != normalize(snapshot['question']):
            raise ConnectorError('Question ID/text no longer matches the live session; answer was not submitted')
        self.ready = (str(snapshot['external_id']), snapshot['question'])

    def submit(self, snapshot, key):
        identity = (str(snapshot['external_id']), snapshot['question'])
        if getattr(self, 'ready', None) != identity:
            raise ConnectorError('Verify the current question before submitting')
        self.ready = None  # Never retry an answer automatically.
        answer = json.loads(snapshot['content'])['candidate_input']
        if not answer.strip():
            raise ConnectorError('The interview API requires a nonempty answer')
        payload = {'question_id': int(snapshot['external_id']), 'question_text': snapshot['question'],
                   'user_answer': answer, 'level_rank': int(self.config.get('level_rank', 2))}
        data = self.request('POST', '/api/evaluate', json=payload, headers={'Idempotency-Key': key})
        if not isinstance(data, dict) or not isinstance(data.get('concept_evaluations'), list) or not isinstance(data.get('sections'), dict):
            raise ConnectorError('Unsupported coaching response; inspect the submission before retrying')
        concepts = data['concept_evaluations']
        level = int(self.config.get('level_rank', 2))
        visible = [c for c in concepts if int(c.get('level', 1)) <= level or
                   str(c.get('status', '')).lower().strip() in ('covered', 'partially covered', 'incorrectly explained')]
        return {'output': json.dumps(data, ensure_ascii=False), 'feedback': data['sections'],
                'concept_evaluations': concepts, 'visible_concept_evaluations': visible,
                'request_question_id': snapshot['external_id'], 'request_question': snapshot['question'],
                'level_rank': level, 'transport': 'interview_api',
                'question_id': data.get('question_id'),
                'concepts': {c['text']: c['status'] for c in visible},
                'counts': {status: sum(str(c['status']).lower().strip() == status for c in visible)
                           for status in ('covered', 'partially covered', 'not covered', 'incorrectly explained')}}
