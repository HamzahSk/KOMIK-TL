import axios from 'axios';
import fs from 'fs/promises';
import path from 'path';

// Pengganti Enum dari TypeScript
export const ALGORITHM_LIST = {
   V1: 'DeepSeekHashV1'
};

export const ENDPOINTS = {
   CREATE_POW: '/chat/create_pow_challenge',
   CREATE_SESSION: '/chat_session/create',
   COMPLETION: '/chat/completion',
   COMPLETION2: '/api/v0/chat/completion'
};

export const STREAM_ACTIONS = {
   APPEND: 'APPEND'
};

export const FRAGMENT_TYPES = {
   RESPONSE: 'RESPONSE'
};

export class WasmInitError extends Error {
   constructor(message) {
      super(`[WASM_INIT_ERROR]: ${message}`);
      this.name = this.constructor.name;
   }
}

export class PowCalcError extends Error {
   constructor(message) {
      super(`[POW_CALC_ERROR]: ${message}`);
      this.name = this.constructor.name;
   }
}

export class AbstractSolver {
   async init(wasmPath) {
      throw new Error("Method 'init()' must be implemented.");
   }
   async solveAndFormatHeader(data) {
      throw new Error("Method 'solveAndFormatHeader()' must be implemented.");
   }
}

export class DeepSeekSolver extends AbstractSolver {
   constructor() {
      super();
      this.textEncoder = new TextEncoder();
      this.memoryCache = null;
      this.wasmInstance = null;
      this.currentOffset = 0;
   }

   async init(wasmPath) {
      try {
         const imports = { wbg: {} };
         const buffer = await fs.readFile(wasmPath);
         const { instance: instance } = await WebAssembly.instantiate(buffer, imports);
         this.wasmInstance = instance.exports;
         return this.wasmInstance;
      } catch (error) {
         throw new WasmInitError(error instanceof Error ? error.message : 'Unknown error');
      }
   }

   getMemory() {
      if (!this.wasmInstance) throw new WasmInitError('Instance not initialized');
      if (this.memoryCache === null || this.memoryCache.byteLength === 0) {
         this.memoryCache = new Uint8Array(this.wasmInstance.memory.buffer);
      }
      return this.memoryCache;
   }

   encodeString(text, allocate, reallocate) {
      if (!reallocate) {
         const encoded = this.textEncoder.encode(text);
         const ptr = allocate(encoded.length, 1) >>> 0;
         const memory = this.getMemory();
         memory.subarray(ptr, ptr + encoded.length).set(encoded);
         this.currentOffset = encoded.length;
         return ptr;
      }

      const stringLength = text.length;
      let ptr = allocate(stringLength, 1) >>> 0;
      const memory = this.getMemory();
      let asciiLength = 0;

      while (asciiLength < stringLength) {
         const charCode = text.charCodeAt(asciiLength);
         if (charCode > 127) break;
         memory[ptr + asciiLength] = charCode;
         asciiLength++;
      }

      if (asciiLength !== stringLength) {
         if (asciiLength > 0) text = text.slice(asciiLength);
         ptr = reallocate(ptr, stringLength, asciiLength + text.length * 3, 1) >>> 0;
         const subarray = this.getMemory().subarray(ptr + asciiLength, ptr + asciiLength + text.length * 3);
         const result = this.textEncoder.encodeInto(text, subarray);
         asciiLength += result.written ?? 0;
         ptr = reallocate(ptr, asciiLength + text.length * 3, asciiLength, 1) >>> 0;
      }
      this.currentOffset = asciiLength;
      return ptr;
   }

   calculateHash(algorithm, challenge, salt, difficulty, expireAt) {
      if (algorithm !== ALGORITHM_LIST.V1) {
         throw new PowCalcError(`Unsupported algorithm: ${algorithm}`);
      }
      if (!this.wasmInstance) {
         throw new WasmInitError('WASM is not initialized');
      }

      const prefix = `${salt}_${expireAt}_`;
      try {
         const retptr = this.wasmInstance.__wbindgen_add_to_stack_pointer(-16);

         const ptr0 = this.encodeString(
            challenge,
            this.wasmInstance.__wbindgen_export_0.bind(this.wasmInstance),
            this.wasmInstance.__wbindgen_export_1.bind(this.wasmInstance)
         );
         const len0 = this.currentOffset;

         const ptr1 = this.encodeString(
            prefix,
            this.wasmInstance.__wbindgen_export_0.bind(this.wasmInstance),
            this.wasmInstance.__wbindgen_export_1.bind(this.wasmInstance)
         );
         const len1 = this.currentOffset;

         this.wasmInstance.wasm_solve(retptr, ptr0, len0, ptr1, len1, difficulty);

         const dataView = new DataView(this.wasmInstance.memory.buffer);
         const status = dataView.getInt32(retptr + 0, true);
         const value = dataView.getFloat64(retptr + 8, true);

         if (status === 0) return undefined;
         return value;
      } finally {
         this.wasmInstance.__wbindgen_add_to_stack_pointer(16);
      }
   }

   async solveAndFormatHeader(challengeData) {
      const data = 'challenge' in challengeData && typeof challengeData.challenge === 'string'
         ? challengeData
         : challengeData.challenge;

      const { algorithm, challenge, salt, difficulty, expire_at, signature, target_path } = data;

      const answer = this.calculateHash(algorithm, challenge, salt, difficulty, expire_at);
      if (answer === undefined) throw new PowCalcError('Failed to find answer');

      const payload = {
         algorithm,
         challenge,
         salt,
         answer: answer,
         signature,
         target_path
      };

      return Buffer.from(JSON.stringify(payload)).toString('base64');
   }
}

export class DeepSeekClient {
   constructor() {
      this.authKey = null;
      this.solver = new DeepSeekSolver();
      this.wasmPath = path.resolve(process.cwd(), './lib/chatbot/sha3_wasm_bg.wasm');
      
      this.client = axios.create({
         baseURL: 'https://chat.deepseek.com/api/v0',
         headers: {
            'x-app-version': '2.0.0',
            'x-client-locale': 'en_US',
            'x-client-platform': 'web',
            'x-client-timezone-offset': '25200',
            'x-client-version': '2.0.0'
         },
         timeout: 30000
      });
   }

   buildMessage(message, status = false, data) {
      return { creator: global.creator, status: status, msg: message, ...(data && { data: data }) };
   }

   async bind(auth) {
      this.authKey = auth;
   }

   extractTextFromStream(rawData) {
      let accumulatedText = "";
      const streamLines = rawData.split('\n');

      for (const singleLine of streamLines) {
         if (singleLine.startsWith('data: ')) {
            const extractedJson = singleLine.substring(6).trim();
            if (!extractedJson) continue;

            try {
               const parsedObject = JSON.parse(extractedJson);

               if (
                  typeof parsedObject.v === 'object' &&
                  parsedObject.v?.response?.fragments &&
                  Array.isArray(parsedObject.v.response.fragments)
               ) {
                  const responseFragment = parsedObject.v.response.fragments.find(
                     (fragment) => fragment.type === FRAGMENT_TYPES.RESPONSE
                  );
                  if (responseFragment?.content) {
                     accumulatedText += responseFragment.content;
                  }
               } else if (parsedObject.o === STREAM_ACTIONS.APPEND && typeof parsedObject.v === "string") {
                  accumulatedText += parsedObject.v;
               } else if (typeof parsedObject.v === "string" && !parsedObject.o && !parsedObject.p) {
                  accumulatedText += parsedObject.v;
               }
            } catch (error) {
               return null;
            }
         }
      }
      return accumulatedText || null;
   }

   async getToken() {
      try {
         await this.solver.init(this.wasmPath);
         const response = await this.client.post(
            ENDPOINTS.CREATE_POW,
            { target_path: ENDPOINTS.COMPLETION2 },
            { headers: { authorization: `Bearer ${this.authKey}` } }
         );
         

         const bizData = response.data?.data?.biz_data;
         if (!bizData) return null;

         return (await this.solver.solveAndFormatHeader(bizData)) ?? null;
      } catch (error) {
         return null;
      }
   }

   async newChat() {
      if (!this.authKey) return this.buildMessage('Authorization required!');

      const token = await this.getToken();
      if (!token) return this.buildMessage("Can't solve PoW!");

      try {
         const response = await this.client.post(
            ENDPOINTS.CREATE_SESSION,
            {},
            { headers: { authorization: `Bearer ${this.authKey}`, 'x-ds-pow-response': token } }
         );

         const session = response.data?.data?.biz_data?.chat_session;
         if (!session) return this.buildMessage("Can't create chat session!");

         return {
            creator: global.creator,
            status: true,
            data: { ...session, token: token }
         };
      } catch (error) {
         return this.buildMessage('Something went wrong!');
      }
   }

   async chat(prompt, id = null) {
      if (!this.authKey) return this.buildMessage('Authorization required!');

      let sessionId = id;
      let powToken = null;

      if (!sessionId) {
         const session = await this.newChat();
         if (!session.status || !session.data) return this.buildMessage(session.msg ?? 'Failed');
         sessionId = session.data.id;
         powToken = session.data.token;
      } else {
         powToken = await this.getToken();
         if (!powToken) return this.buildMessage("Can't solve PoW!");
      }

      try {
         const response = await this.client.post(
            ENDPOINTS.COMPLETION,
            {
               chat_session_id: sessionId,
               parent_message_id: null,
               model_type: null,
               prompt: prompt,
               ref_file_ids: [],
               thinking_enabled: false,
               search_enabled: false,
               action: null,
               preempt: false
            },
            {
               headers: {
                  authorization: `Bearer ${this.authKey}`,
                  'x-ds-pow-response': powToken
               },
               responseType: 'text' 
            }
         );

         const message = this.extractTextFromStream(response.data);
         if (!message) return this.buildMessage('Sorry, AI unavailable right now!');

         return {
            creator: global.creator,
            status: true,
            data: { id: sessionId, message: message }
         };
      } catch (error) {
         return this.buildMessage('Something went wrong!');
      }
   }
}

export default new DeepSeekClient();
