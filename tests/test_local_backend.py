import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import local_backend as lb


class LocalBackendTests(unittest.TestCase):
    def setUp(self):
        lb._cache.clear()

    def test_exo_discovers_only_active_instances(self):
        inventory = {'data': [{'id': 'loaded', 'owned_by': 'exo'}, {'id': 'unloaded', 'owned_by': 'exo'}]}
        state = {'instances': {'one': {'MlxInstance': {'shardAssignments': {'modelId': 'loaded'}}}}}
        with patch.object(lb, '_request', side_effect=lambda path: iter([inventory if path == 'models' else state])):
            models = lb.discover_local_models(True)
        self.assertEqual([m['cli_model'] for m in models], ['local/loaded'])

    def test_ollama_discovers_thinking_capability_via_api_tags(self):
        models_payload = {
            'data': [
                {'id': 'inkling-2-mini:latest', 'owned_by': 'library'},
                {'id': 'plain-model:latest', 'owned_by': 'library'},
            ]
        }
        tags_payload = {
            'models': [
                {'name': 'inkling-2-mini:latest', 'model': 'inkling-2-mini:latest', 'capabilities': ['completion', 'tools', 'thinking']},
                {'name': 'plain-model:latest', 'model': 'plain-model:latest', 'capabilities': ['completion']},
            ]
        }

        def fake_request(path):
            if path == 'models':
                return iter([models_payload])
            if path == '/api/tags':
                return iter([tags_payload])
            raise AssertionError(f'Unexpected request path: {path}')

        with patch.object(lb, '_request', side_effect=fake_request) as req:
            models = lb.discover_local_models(True)
        self.assertEqual([c.args[0] for c in req.call_args_list], ['models', '/api/tags'])
        self.assertTrue(models[0]['capabilities']['thinking'])
        self.assertFalse(models[1]['capabilities']['thinking'])

    def test_generic_openai_server_does_not_probe_ollama_tags(self):
        with patch.object(lb, '_request', return_value=iter([{'data': [{'id': 'generic-model', 'owned_by': 'vllm'}]}])) as req:
            models = lb.discover_local_models(True)
        req.assert_called_once_with('models')
        self.assertFalse(models[0]['capabilities']['thinking'])
        self.assertFalse(models[0]['capabilities']['vision'])

    def test_discovers_vision_capability_from_name_ollama_and_env(self):
        with patch.object(lb, '_request', return_value=iter([{'data': [{'id': 'deepseek-ai/DeepSeek-V4-Flash-Vision-Exp', 'owned_by': 'vllm'}]}])):
            vllm_vision = lb.discover_local_models(True)
        self.assertTrue(vllm_vision[0]['capabilities']['vision'])

        ollama_models = {'data': [{'id': 'llava-phi:latest', 'owned_by': 'library'}]}
        ollama_tags = {'models': [{'name': 'llava-phi:latest', 'capabilities': ['completion', 'vision']}]}
        with patch.object(lb, '_request', side_effect=lambda p: iter([ollama_models if p == 'models' else ollama_tags])):
            ollama_res = lb.discover_local_models(True)
        self.assertTrue(ollama_res[0]['capabilities']['vision'])

        with patch.dict(os.environ, {'KOOKAI_LOCAL_VISION': '1'}), \
             patch.object(lb, '_request', return_value=iter([{'data': [{'id': 'plain-model', 'owned_by': 'vllm'}]}])):
            forced_on = lb.discover_local_models(True)
        self.assertTrue(forced_on[0]['capabilities']['vision'])

        with patch.dict(os.environ, {'KOOKAI_LOCAL_VISION': '0'}), \
             patch.object(lb, '_request', return_value=iter([{'data': [{'id': 'deepseek-ai/DeepSeek-V4-Flash-Vision-Exp', 'owned_by': 'vllm'}]}])):
            forced_off = lb.discover_local_models(True)
        self.assertFalse(forced_off[0]['capabilities']['vision'])

    def test_unreachable_server_has_no_models(self):
        with patch.object(lb, '_request', side_effect=OSError('offline')):
            self.assertEqual(lb.discover_local_models(True), [])

    def test_aliases_do_not_collide_with_cloud(self):
        with patch.object(lb, '_request', return_value=iter([{'data': [{'id': 'gpt-4'}, {'id': 'gpt-4'}]}])):
            models = lb.discover_local_models(True)
        self.assertEqual(len(models), 1)
        self.assertNotEqual(models[0]['cli_model'], 'gpt-4')

    def test_stream_over_real_http_and_conversation_payload(self):
        captured = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                captured.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n')
                self.wfile.write(b'data: {"choices":[{"delta":{"content":" world"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {'KOOKAI_LOCAL_LLM_URL': f'http://127.0.0.1:{server.server_port}/v1'}):
                messages = [{'role': 'user', 'content': 'prior'}, {'role': 'assistant', 'content': 'reply'}, {'role': 'user', 'content': 'next'}]
                result = lb.complete_local({'cli_model': 'local/test', 'capabilities': {'thinking': False}}, messages)
            self.assertEqual(result, 'hello world')
            self.assertEqual(captured[0][0], '/v1/chat/completions')
            self.assertEqual(captured[0][1]['messages'], messages)
            self.assertEqual(captured[0][1]['model'], 'test')
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_cancelled_request_never_connects(self):
        cancel = threading.Event(); cancel.set()
        with self.assertRaises(lb.LocalRequestCancelled):
            list(lb._request('chat/completions', {}, cancel))

    def test_stream_error_and_truncation_are_not_success(self):
        model = {'cli_model': 'local/test', 'capabilities': {'thinking': False}}
        for events in ([{'error': {'message': 'bad'}}], [{'choices': [{'delta': {'content': 'partial'}}]}], []):
            with self.subTest(events=events), patch.object(lb, '_request', return_value=iter(events)):
                with self.assertRaises(RuntimeError):
                    lb.complete_local(model, [])

class LocalChatIntegrationTests(unittest.TestCase):
    def test_chat_roundtrip_persists_and_restores_history(self):
        import tempfile
        import main
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(main, 'CANONICAL_CONVERSATIONS_FILE', tmp + '/conversations.json'), \
             patch.object(main, 'CONVERSATION_METADATA_FILE', tmp + '/metadata.json'), \
             patch.object(main, 'get_workspace_alignment_context', return_value=''), \
             patch.object(main, 'in_memory_chats', {}), \
             patch.object(main, 'should_use_claude_local_harness', return_value=False), \
             patch.object(main, 'should_use_dsh_harness', return_value=False), \
             patch.object(main, 'should_use_qwen_harness', return_value=False), \
             patch.object(main, 'complete_local', return_value='local reply') as complete, \
             patch.object(main, 'discover_local_models') as discover:
            discover.return_value = [{'id': 'local-test', 'label': 'Test (Local)', 'provider': 'local',
                'cli_model': 'local/test', 'enabled': True, 'capabilities': {
                    'thinking': False, 'thinking_required': False, 'effort': [], 'speed': []}}]
            req = main.ChatRequest(message='first', model='local-test', provider='local',
                                   workspace='KookAI', target='Sandbox', conversation_id='local-test-chat')
            result = main.build_chat_response(req)
            self.assertEqual(result['reply'], 'local reply')
            self.assertEqual(result['provider'], 'local')
            main.in_memory_chats.clear()
            req.message = 'second'
            main.build_chat_response(req)
            sent = complete.call_args.args[1]
            self.assertEqual([m['content'] for m in sent[1:]], ['first', 'local reply', 'second'])
            record = main.get_canonical_conversation('local-test-chat')
            self.assertEqual(len(record['messages']), 4)

    def test_local_harness_roundtrip_persists_and_resumes_qwen_session(self):
        import subprocess
        import tempfile
        import main

        calls = []

        def fake_run_agent(cmd, cwd_path, **kwargs):
            calls.append((list(cmd), cwd_path, kwargs.get('stdin_text', '')))
            out = "\n".join([
                json.dumps({"type": "system", "subtype": "init", "session_id": "qwen-ses-1"}),
                json.dumps({"type": "result", "subtype": "success", "session_id": "qwen-ses-1", "is_error": False, "result": "harness reply"}),
            ])
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(main, 'CANONICAL_CONVERSATIONS_FILE', tmp + '/conversations.json'), \
             patch.object(main, 'CONVERSATION_METADATA_FILE', tmp + '/metadata.json'), \
             patch.object(main, 'get_workspace_alignment_context', return_value=''), \
             patch.object(main, 'in_memory_chats', {}), \
             patch.object(main, 'convo_id_mapping', {}), \
             patch.object(main, 'should_use_claude_local_harness', return_value=False), \
             patch.object(main, 'should_use_dsh_harness', return_value=False), \
             patch.object(main, 'should_use_qwen_harness', return_value=True), \
             patch.object(main, 'resolve_qwen_executable', return_value='/usr/local/bin/qwen'), \
             patch.object(main, 'run_agent_command', side_effect=fake_run_agent), \
             patch.object(main, 'discover_local_models') as discover:
            discover.return_value = [{'id': 'local-test', 'label': 'Test (Local)', 'provider': 'local',
                'cli_model': 'local/qwen-local', 'enabled': True, 'capabilities': {
                    'thinking': False, 'thinking_required': False, 'effort': [], 'speed': []}}]
            req1 = main.ChatRequest(message='edit file', model='local-test', provider='local',
                                    workspace='KookAI', target='Sandbox', conversation_id='temp-local-1')
            res1 = main.build_chat_response(req1)
            self.assertEqual(res1['reply'], 'harness reply')
            self.assertEqual(res1['provider'], 'local')
            self.assertEqual(res1['conversation_id'], 'local_qwen_qwen-ses-1')
            self.assertIn('auto-edit', calls[0][0])
            self.assertNotIn('--resume', calls[0][0])
            record = main.get_canonical_conversation('local_qwen_qwen-ses-1')
            self.assertEqual(len(record['messages']), 2)

            req2 = main.ChatRequest(message='run tests', model='local-test', provider='local',
                                    workspace='KookAI', target='Real', conversation_id='local_qwen_qwen-ses-1')
            res2 = main.build_chat_response(req2)
            self.assertEqual(res2['conversation_id'], 'local_qwen_qwen-ses-1')
            self.assertIn('yolo', calls[1][0])
            resume_idx = calls[1][0].index('--resume')
            self.assertEqual(calls[1][0][resume_idx + 1], 'qwen-ses-1')

    def test_local_failure_never_falls_back_to_cloud(self):
        import main
        with patch.object(main, 'run_local_llm', side_effect=RuntimeError('offline')), \
             patch.object(main, 'is_provider_available') as available:
            result, _ = main.run_selected_cli('private prompt', 'local-test', 'test', 'Sandbox', 'KookAI', 'local')
            self.assertIn('offline', result)
            available.assert_not_called()

    def test_cancel_propagates_without_fallback(self):
        import main
        event = threading.Event(); event.set()
        with self.assertRaises(main.AgentCommandCancelled):
            main.run_selected_cli('hello', 'local-test', 'test', 'Sandbox', 'KookAI', 'local', cancel_event=event)

    def test_legacy_catalog_excludes_local_unless_requested(self):
        import asyncio
        import main
        from types import SimpleNamespace
        catalog = {'schema_version': 1, 'catalog_version': 'test', 'default_model': 'cloud', 'models': [
            {'id': 'cloud', 'provider': 'agy', 'enabled': True},
            {'id': 'local-test', 'provider': 'local', 'enabled': True}]}
        with patch.object(main, 'load_runtime_model_catalog', side_effect=lambda: json.loads(json.dumps(catalog))), \
             patch.object(main, '_last_models_sync_check_time', float('inf')):
            req = SimpleNamespace(headers={}, query_params={}, client=SimpleNamespace(host='127.0.0.1'))
            legacy = json.loads(asyncio.run(main.get_models(req)).body)
            current = json.loads(asyncio.run(main.get_models(req, include_local=True)).body)
        self.assertEqual(len(legacy['models']), 1)
        self.assertEqual(len(current['models']), 2)

    def test_cancellation_interrupts_a_waiting_http_response(self):
        import time
        started = threading.Event()
        release = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                started.set()
                release.wait(5)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        cancel = threading.Event()
        errors = []
        def request():
            try:
                list(lb._request('chat/completions', {}, cancel))
            except Exception as exc:
                errors.append(exc)
        try:
            with patch.dict(os.environ, {'KOOKAI_LOCAL_LLM_URL': f'http://127.0.0.1:{server.server_port}/v1'}):
                client = threading.Thread(target=request)
                client.start()
                self.assertTrue(started.wait(2))
                cancel.set()
                client.join(2)
                self.assertFalse(client.is_alive())
                self.assertIsInstance(errors[0], lb.LocalRequestCancelled)
        finally:
            release.set()
            server.shutdown(); server.server_close(); worker.join()
