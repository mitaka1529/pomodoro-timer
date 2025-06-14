class PomodoroTimer {
    constructor() {
        this.workTime = 25 * 60; // 作業時間(25分)
        this.breakTime = 5 * 60; // 休憩時間(5分)
        this.isWorking = true;
        this.isRunning = false;
        this.interval = null;

        this.initializeElements();
        this.initializeEventListeners();
    }

    initializeElements() {
        this.timeDisplay = document.getElementById('time-display');
        this.startBtn = document.getElementById('start-btn');
        this.pauseBtn = document.getElementById('pause-btn');
        this.resetBtn = document.getElementById('reset-btn');
        this.workTimeInput = document.getElementById('work-time');
        this.breakTimeInput = document.getElementById('break-time');
    }

    initializeEventListeners() {
        this.startBtn.addEventListener('click', () => this.start());
        this.pauseBtn.addEventListener('click', () => this.pause());
        this.resetBtn.addEventListener('click', () => this.reset());
        this.workTimeInput.addEventListener('change', () => this.updateWorkTime());
        this.breakTimeInput.addEventListener('change', () => this.updateBreakTime());
    }

    start() {
        if (this.isRunning) return;
        this.isRunning = true;
        this.interval = setInterval(() => this.tick(), 1000);
    }

    pause() {
        if (!this.isRunning) return;
        this.isRunning = false;
        clearInterval(this.interval);
    }

    reset() {
        this.pause();
        this.isWorking = true;
        this.workTime = parseInt(this.workTimeInput.value) * 60;
        this.breakTime = parseInt(this.breakTimeInput.value) * 60;
        this.updateDisplay();
    }

    updateWorkTime() {
        if (!this.isRunning) {
            this.workTime = parseInt(this.workTimeInput.value) * 60;
            this.updateDisplay();
        }
    }

    updateBreakTime() {
        if (!this.isRunning) {
            this.breakTime = parseInt(this.breakTimeInput.value) * 60;
            this.updateDisplay();
        }
    }

    tick() {
        if (this.isWorking) {
            if (this.workTime > 0) {
                this.workTime--;
            } else {
                // 作業時間終了
                this.isWorking = false;
                this.workTime = parseInt(this.workTimeInput.value) * 60;
                this.breakTime = parseInt(this.breakTimeInput.value) * 60;
                alert('作業時間終了！休憩時間へ移行します。');
            }
        } else {
            if (this.breakTime > 0) {
                this.breakTime--;
            } else {
                // 休憩時間終了
                this.isWorking = true;
                this.workTime = parseInt(this.workTimeInput.value) * 60;
                this.breakTime = parseInt(this.breakTimeInput.value) * 60;
                alert('休憩時間終了！作業時間へ移行します。');
            }
        }
        this.updateDisplay();
    }

    updateDisplay() {
        const time = this.isWorking ? this.workTime : this.breakTime;
        const minutes = Math.floor(time / 60);
        const seconds = time % 60;
        this.timeDisplay.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }
}

// インスタンス化
const pomodoroTimer = new PomodoroTimer();
