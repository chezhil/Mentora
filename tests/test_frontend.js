// Simple zero-dependency test runner for AITutorAvatar

// Mock the DOM and Three.js
global.document = {
    getElementById: (id) => {
        if (id === 'avatar-canvas') {
            return {
                parentElement: { clientWidth: 800, clientHeight: 600 },
                style: {}
            };
        }
        return {
            style: {},
            addEventListener: () => {},
            innerHTML: '',
            appendChild: () => {}
        };
    },
    createElement: () => ({ style: {}, className: '' })
};
global.window = {
    devicePixelRatio: 1,
    addEventListener: () => {},
    AudioContext: class {
        createMediaElementSource() { return { connect: () => {} }; }
        createAnalyser() { return { fftSize: 256, connect: () => {}, frequencyBinCount: 128, getByteFrequencyData: () => {} }; }
    }
};
global.requestAnimationFrame = (cb) => {}; // Mock rAF
global.Audio = class {
    constructor() { this.paused = false; this.ended = false; }
    play() {}
};

// Mock Three.js minimally
global.THREE = {
    Scene: class { add() {} },
    Color: class {},
    PerspectiveCamera: class { position = { set: () => {} }; updateProjectionMatrix() {} },
    WebGLRenderer: class { setSize() {}; setPixelRatio() {}; render() {} },
    AmbientLight: class {},
    DirectionalLight: class { position = { set: () => {} } },
    Group: class { add() {}; rotation = { set: () => {} }; },
    BoxGeometry: class {},
    CylinderGeometry: class {},
    MeshStandardMaterial: class {},
    Mesh: class { position = { set: () => {} }; scale = { y: 1, x: 1 }; rotation = { set: () => {}, x: 0, y: 0, z: 0 }; }
};

// Import the component (assuming Node context for tests, we use fs and eval)
const fs = require('fs');
const code = fs.readFileSync('frontend/AITutorAvatar.js', 'utf8');
eval(code); // Evaluates and creates global.AITutorAvatar

console.log("Running Frontend Component Tests...");

function runTests() {
    let passed = 0;
    let failed = 0;

    function assert(condition, message) {
        if (condition) {
            passed++;
        } else {
            console.error("❌ FAILED: " + message);
            failed++;
        }
    }

    try {
        const config = {
            canvasId: 'avatar-canvas',
            transcriptBoxId: 'chat-history',
            promptInputId: 'prompt-input',
            micBtnId: 'ptt-btn',
            sendBtnId: 'send-btn'
        };

        const avatar = new window.AITutorAvatar(config);

        // Test 1: Initialization
        assert(avatar.isListening === false, "Initial state should not be listening");
        assert(avatar.currentGesture === null, "Initial gesture should be null");
        console.log("✅ Passed Initialization State");

        // Test 2: Trigger Gesture
        avatar.triggerGesture("nod");
        assert(avatar.currentGesture === "nod", "Gesture state should update on trigger");
        assert(avatar.gestureTimer === 0, "Gesture timer should reset on trigger");
        console.log("✅ Passed Gesture State Trigger");

        // Test 3: Audio & Lip Sync setup
        const fakeGestures = [{ type: "smile", index: 10 }];
        avatar.playAudio("/dummy.wav", fakeGestures);
        assert(avatar.activeGestures.length === 1, "Should queue active gestures on audio play");
        assert(avatar.audioCtx !== null, "Should initialize AudioContext");
        console.log("✅ Passed Audio Playback Setup");

    } catch (e) {
        console.error(e);
        failed++;
    }

    console.log(`\nTests complete: ${passed} passed, ${failed} failed.`);
    if (failed > 0) process.exit(1);
}

runTests();
