import deepseek from './deepsek.js'; // Pastikan nama file sesuai (misal: deepseek.js)
// https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm
const prompt = `Terjemahkan teks di bawah ini ke dalam bahasa Indonesia dengan ketentuan berikut:
`

async function main() {
  // Masukkan token Bearer yang tadi disalin
  await deepseek.bind('fR3AbopXw9y9behMnDFGnTMf3p+NnKwhKh92h/gTOZKwXZED8yRx3WkdVJHaau') // nanti apikey nya dipilih random yah, jadi tiap selesai 1 chapter, ganti apikey 

  // Panggil fungsi chat dengan prompt kamu
  const res = await deepseek.chat(prompt);

  console.log(JSON.stringify(res, null, 2));
}

main();


responnya 
.../PROJEK/deepsek $ node chat.js
{
  "status": true,
  "data": {
    "id": "f9277ccf-223c-4b13-aa2e-59b0c612a48d",
    "message": "Sepertinya Anda belum menyertakan teks yang ingin diterjemahkan. Silakan kirimkan teksnya, dan saya akan menerjemahkannya ke dalam bahasa Indonesia sesuai ketentuan yang Anda berikan."
  }
}
.../PROJEK/deepsek $
