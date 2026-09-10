import { expect, test } from 'vitest'
import { decodeFrame } from './camera'

test('decodes big endian metadata and JPEG payload', () => { const json = new TextEncoder().encode(JSON.stringify({ frame_id: 'f1', captured_at: null, received_at: 'now', width: 2, height: 1 })); const bytes = new Uint8Array(4 + json.length + 4); new DataView(bytes.buffer).setUint32(0, json.length); bytes.set(json, 4); bytes.set([255, 216, 255, 217], 4 + json.length); const frame = decodeFrame(bytes.buffer); expect(frame.metadata.frame_id).toBe('f1'); expect(frame.jpeg.byteLength).toBe(4) })
test('rejects malformed and oversized metadata safely', () => { expect(() => decodeFrame(new Uint8Array([0, 0, 0]).buffer)).toThrow(); const bytes = new Uint8Array(4); new DataView(bytes.buffer).setUint32(0, 100_001); expect(() => decodeFrame(bytes.buffer)).toThrow() })
