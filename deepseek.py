import os
import json
import base64
import struct
import requests
from wasmtime import Engine, Store, Module, Instance

# Pengganti Enum dari TypeScript/JavaScript
ALGORITHM_LIST = {
    'V1': 'DeepSeekHashV1'
}

ENDPOINTS = {
    'CREATE_POW': '/chat/create_pow_challenge',
    'CREATE_SESSION': '/chat_session/create',
    'COMPLETION': '/chat/completion',
    'COMPLETION2': '/api/v0/chat/completion'
}

STREAM_ACTIONS = {
    'APPEND': 'APPEND'
}

FRAGMENT_TYPES = {
    'RESPONSE': 'RESPONSE'
}

# Variabel global untuk meniru `global.creator` pada JS
CREATOR = "YourName" 

class WasmInitError(Exception):
    def __init__(self, message):
        super().__init__(f"[WASM_INIT_ERROR]: {message}")

class PowCalcError(Exception):
    def __init__(self, message):
        super().__init__(f"[POW_CALC_ERROR]: {message}")

class AbstractSolver:
    def init(self, wasm_path: str):
        raise NotImplementedError("Method 'init()' must be implemented.")
        
    def solve_and_format_header(self, data: dict) -> str:
        raise NotImplementedError("Method 'solve_and_format_header()' must be implemented.")

class DeepSeekSolver(AbstractSolver):
    def __init__(self):
        super().__init__()
        self.engine = Engine()
        self.store = Store(self.engine)
        self.instance = None
        self.memory = None

    def init(self, wasm_path: str):
        try:
            with open(wasm_path, 'rb') as f:
                wasm_bytes = f.read()
            
            module = Module(self.engine, wasm_bytes)
            # JS menggunakan imports { wbg: {} }, di Wasmtime kita perlu mock module jika diminta
            # Untuk wbindgen standar tanpa dependensi luar, array kosong cukup.
            self.instance = Instance(self.store, module, [])
            self.memory = self.instance.exports(self.store)["memory"]
            return self.instance
        except Exception as e:
            raise WasmInitError(str(e))

    def encode_string(self, text: str, allocate_func) -> tuple[int, int]:
        """
        Versi Python dari encodeString. 
        Menggunakan utf-8 encode dan menulis langsung ke memori Wasm.
        Mengembalikan pointer dan panjang string.
        """
        encoded = text.encode('utf-8')
        length = len(encoded)
        ptr = allocate_func(self.store, length, 1)
        
        # Tulis byte ke dalam memori wasm
        self.memory.write(self.store, ptr, encoded)
        return ptr, length

    def calculate_hash(self, algorithm: str, challenge: str, salt: str, difficulty: int, expire_at: int):
        if algorithm != ALGORITHM_LIST['V1']:
            raise PowCalcError(f"Unsupported algorithm: {algorithm}")
        if not self.instance:
            raise WasmInitError("WASM is not initialized")

        prefix = f"{salt}_{expire_at}_"
        exports = self.instance.exports(self.store)
        
        add_to_stack_pointer = exports["__wbindgen_add_to_stack_pointer"]
        allocate = exports["__wbindgen_export_0"]
        wasm_solve = exports["wasm_solve"]

        try:
            # Geser stack pointer sebesar -16 byte untuk alokasi return value
            retptr = add_to_stack_pointer(self.store, -16)

            ptr0, len0 = self.encode_string(challenge, allocate)
            ptr1, len1 = self.encode_string(prefix, allocate)

            # Eksekusi fungsi solver dari WASM
            wasm_solve(self.store, retptr, ptr0, len0, ptr1, len1, difficulty)

            # Membaca hasil dari memori pointer return (16 bytes)
            data = self.memory.read(self.store, retptr, retptr + 16)
            
            # Unpack byte array ke status (int32) dan value (float64)
            status = struct.unpack_from("<i", data, 0)[0]
            value = struct.unpack_from("<d", data, 8)[0]

            if status == 0:
                return None
            return value
        finally:
            # Kembalikan stack pointer
            add_to_stack_pointer(self.store, 16)

    def solve_and_format_header(self, challenge_data: dict) -> str:
        data = challenge_data if 'algorithm' in challenge_data else challenge_data.get('challenge', {})

        algorithm = data.get('algorithm')
        challenge = data.get('challenge')
        salt = data.get('salt')
        difficulty = data.get('difficulty')
        expire_at = data.get('expire_at')
        signature = data.get('signature')
        target_path = data.get('target_path')

        answer = self.calculate_hash(algorithm, challenge, salt, difficulty, expire_at)
        if answer is None:
            raise PowCalcError("Failed to find answer")

        payload = {
            "algorithm": algorithm,
            "challenge": challenge,
            "salt": salt,
            "answer": answer,
            "signature": signature,
            "target_path": target_path
        }

        # Format ke base64 string
        json_payload = json.dumps(payload, separators=(',', ':'))
        return base64.b64encode(json_payload.encode('utf-8')).decode('utf-8')


class DeepSeekClient:
    def __init__(self):
        self.auth_key = None
        self.solver = DeepSeekSolver()
        # Mengubah path menggunakan standard os.path Python
        self.wasm_path = os.path.abspath(os.path.join(os.getcwd(), 'lib', 'chatbot', 'sha3_wasm_bg.wasm'))
        
        self.session = requests.Session()
        self.base_url = 'https://chat.deepseek.com/api/v0'
        self.session.headers.update({
            'x-app-version': '2.0.0',
            'x-client-locale': 'en_US',
            'x-client-platform': 'web',
            'x-client-timezone-offset': '25200',
            'x-client-version': '2.0.0'
        })
        self.timeout = 30

    def build_message(self, message: str, status: bool = False, data: dict = None) -> dict:
        result = {'creator': CREATOR, 'status': status, 'msg': message}
        if data is not None:
            result['data'] = data
        return result

    def bind(self, auth: str):
        self.auth_key = auth

    def extract_text_from_stream(self, raw_data: str) -> str:
        accumulated_text = ""
        stream_lines = raw_data.split('\n')

        for single_line in stream_lines:
            if single_line.startswith('data: '):
                extracted_json = single_line[6:].strip()
                if not extracted_json:
                    continue

                try:
                    parsed_object = json.loads(extracted_json)

                    v_data = parsed_object.get('v')
                    if isinstance(v_data, dict) and isinstance(v_data.get('response', {}).get('fragments'), list):
                        fragments = v_data['response']['fragments']
                        for fragment in fragments:
                            if fragment.get('type') == FRAGMENT_TYPES['RESPONSE'] and fragment.get('content'):
                                accumulated_text += fragment['content']
                                
                    elif parsed_object.get('o') == STREAM_ACTIONS['APPEND'] and isinstance(v_data, str):
                        accumulated_text += v_data
                        
                    elif isinstance(v_data, str) and not parsed_object.get('o') and not parsed_object.get('p'):
                        accumulated_text += v_data
                        
                except json.JSONDecodeError:
                    return None
                    
        return accumulated_text if accumulated_text else None

    def get_token(self):
        try:
            self.solver.init(self.wasm_path)
            
            url = f"{self.base_url}{ENDPOINTS['CREATE_POW']}"
            headers = {'authorization': f'Bearer {self.auth_key}'}
            payload = {'target_path': ENDPOINTS['COMPLETION2']}
            
            response = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            
            biz_data = response.json().get('data', {}).get('biz_data')
            if not biz_data:
                return None

            return self.solver.solve_and_format_header(biz_data)
        except Exception:
            return None

    def new_chat(self):
        if not self.auth_key:
            return self.build_message('Authorization required!')

        token = self.get_token()
        if not token:
            return self.build_message("Can't solve PoW!")

        try:
            url = f"{self.base_url}{ENDPOINTS['CREATE_SESSION']}"
            headers = {
                'authorization': f'Bearer {self.auth_key}',
                'x-ds-pow-response': token
            }
            
            response = self.session.post(url, json={}, headers=headers, timeout=self.timeout)
            response.raise_for_status()

            session_data = response.json().get('data', {}).get('biz_data', {}).get('chat_session')
            if not session_data:
                return self.build_message("Can't create chat session!")

            session_data['token'] = token
            return self.build_message('Success', status=True, data=session_data)
            
        except Exception:
            return self.build_message('Something went wrong!')

    def chat(self, prompt: str, chat_id: str = None):
        if not self.auth_key:
            return self.build_message('Authorization required!')

        session_id = chat_id
        pow_token = None

        if not session_id:
            session_response = self.new_chat()
            if not session_response.get('status') or not session_response.get('data'):
                return self.build_message(session_response.get('msg', 'Failed'))
                
            session_id = session_response['data'].get('id')
            pow_token = session_response['data'].get('token')
        else:
            pow_token = self.get_token()
            if not pow_token:
                return self.build_message("Can't solve PoW!")

        try:
            url = f"{self.base_url}{ENDPOINTS['COMPLETION']}"
            headers = {
                'authorization': f'Bearer {self.auth_key}',
                'x-ds-pow-response': pow_token
            }
            payload = {
                'chat_session_id': session_id,
                'parent_message_id': None,
                'model_type': None,
                'prompt': prompt,
                'ref_file_ids': [],
                'thinking_enabled': False,
                'search_enabled': False,
                'action': None,
                'preempt': False
            }
            
            response = self.session.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()

            message = self.extract_text_from_stream(response.text)
            if not message:
                return self.build_message('Sorry, AI unavailable right now!')

            return self.build_message('Success', status=True, data={'id': session_id, 'message': message})
            
        except Exception:
            return self.build_message('Something went wrong!')

# Untuk penggunaan layaknya export default di Node.js
deepseek_client = DeepSeekClient()
