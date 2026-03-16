/**
 * AudioWorklet processor for mic capture.
 * Buffers 128-sample frames into ~4096-sample chunks before sending.
 * Gemini Live requires continuous audio to keep the session alive.
 */
class MicProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(4096);
    this._offset = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) return true;

    const float32 = input[0]; // 128 samples per call

    // Accumulate into buffer
    const remaining = this._buffer.length - this._offset;
    const toCopy = Math.min(float32.length, remaining);
    this._buffer.set(float32.subarray(0, toCopy), this._offset);
    this._offset += toCopy;

    // Flush when buffer is full (~256ms at 16kHz)
    if (this._offset >= this._buffer.length) {
      const int16 = new Int16Array(this._buffer.length);
      for (let i = 0; i < this._buffer.length; i++) {
        const s = Math.max(-1, Math.min(1, this._buffer[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      this.port.postMessage({ type: "audio", buffer: int16.buffer }, [int16.buffer]);
      this._offset = 0;
    }

    return true;
  }
}

registerProcessor("mic-processor", MicProcessor);
