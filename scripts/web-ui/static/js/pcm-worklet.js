/**
 * AudioWorklet processor that receives interleaved PCM data from the main
 * thread (via postMessage) and outputs it as multi-channel audio.
 *
 * Message format: Float32Array of interleaved samples (3 channels).
 * Ported from poc/static/index.html PcmFeeder pattern.
 */

class PcmFeeder extends AudioWorkletProcessor {
    constructor() {
        super();
        this.buf = [];
        this.offset = 0;
        this.channels = 3;
        this.maxQueue = 32;
        this.port.onmessage = (e) => {
            this.buf.push(e.data);
            while (this.buf.length > this.maxQueue) {
                this.buf.shift();
                this.offset = 0;
            }
        };
    }

    process(inputs, outputs) {
        const out = outputs[0];
        const frames = out[0].length;
        let written = 0;

        while (written < frames && this.buf.length > 0) {
            const src = this.buf[0];
            const srcFrames = src.length / this.channels;
            const avail = srcFrames - this.offset;
            const take = Math.min(avail, frames - written);

            for (let ch = 0; ch < this.channels; ch++) {
                const outCh = out[ch] || out[0];
                for (let i = 0; i < take; i++) {
                    outCh[written + i] = src[(this.offset + i) * this.channels + ch];
                }
            }

            written += take;
            this.offset += take;
            if (this.offset >= srcFrames) {
                this.buf.shift();
                this.offset = 0;
            }
        }

        // Silence remainder
        for (let ch = 0; ch < this.channels; ch++) {
            const outCh = out[ch] || out[0];
            for (let i = written; i < frames; i++) {
                outCh[i] = 0;
            }
        }

        return true;
    }
}

registerProcessor("pcm-feeder", PcmFeeder);
