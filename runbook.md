# Pinky Control Center 운영 런북

이 런북은 현재 checkout에서 확인 가능한 mock 운영과 T12 ROS/Gazebo 인수 준비를 구분한다. T11 영상 녹화·재생은 범위에 없으며, 브라우저는 rosbridge에 직접 연결하지 않는다. 실물 주행 전에는 로봇 측 정지 래치와 watchdog을 별도로 확인한다.

## 1. 설치와 빌드

Ubuntu 24.04와 Python 3.12를 기준으로 한다. 저장소를 `/opt/pinky-control-platform`에 배치하는 운영 설치는 다음을 따른다.

```bash
cd /opt/pinky-control-platform
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install --upgrade pip
backend/.venv/bin/pip install -e 'backend[dev]'
cd frontend
npm ci
npm run build
cd ..
sudo install -d -o control-center -g control-center /var/lib/pinky-control-center /var/log/pinky-control-center
sudo install -d -m 0750 /etc/pinky-control-center
sudo install -m 0640 deployment/env.example /etc/pinky-control-center/control-center.env
sudo install -m 0640 deployment/robots.ros.example.yaml /etc/pinky-control-center/robots.ros.yaml
sudoedit /etc/pinky-control-center/control-center.env
deployment/scripts/validate-deployment.sh /etc/pinky-control-center/control-center.env
```

`CONTROL_PLATFORM_WORKERS=1`, `robot_1` domain `12`, `robot_2` domain `13`, 서로 다른 rosbridge URL을 바꾸지 않는다. 운영 origin이 HTTPS이면 `CONTROL_PLATFORM_SECURE_COOKIES=1`을 사용한다. 비밀 토큰은 env 또는 호스트 secret manager에서 주입하고 YAML·git·로그에 쓰지 않는다.

## 2. 관리자 계정과 mock 기동

계정 생성은 호스트 터미널에서 비밀번호를 직접 입력하는 일회성 명령으로 실행한다.

```bash
cd /opt/pinky-control-platform
backend/.venv/bin/python -m pinky_control_center.main \
  --database /var/lib/pinky-control-center/control.db \
  --reset-password operator --password '<터미널에서만 입력>' --role ADMIN
CONTROL_PLATFORM_DATABASE=/var/lib/pinky-control-center/control.db \
CONTROL_PLATFORM_MODE=mock CONTROL_PLATFORM_HOST=127.0.0.1 \
CONTROL_PLATFORM_PORT=8081 CONTROL_PLATFORM_ALLOWED_ORIGIN=http://localhost:5173 \
CONTROL_PLATFORM_SECURE_COOKIES=0 CONTROL_PLATFORM_WORKERS=1 \
deployment/scripts/start-backend.sh
```

개발 브라우저는 별도 터미널에서 `cd frontend && npm run dev`로 열고 `http://localhost:5173`을 사용한다. API의 `/health`가 `{"status":"ok","mode":"mock"}`를 반환하고 로그인 후 지도·두 카메라·MOCK 상태를 확인한다. 새 환경의 최소 검증은 다음 한 명령으로 실행한다.

```bash
deployment/scripts/acceptance.sh
```

## 3. TLS 동일 출처 배포

`deployment/nginx/control-platform.conf`를 nginx sites-enabled에 설치하고 인증서 경로와 `server_name`을 실제 값으로 바꾼다. 정적 UI, `/api/`, `/ws/`는 모두 같은 HTTPS origin에서 제공하며 backend 포트 8081은 loopback에만 바인딩한다.

```bash
sudo install -m 0644 deployment/nginx/control-platform.conf /etc/nginx/sites-available/pinky-control-center
sudo ln -sf /etc/nginx/sites-available/pinky-control-center /etc/nginx/sites-enabled/pinky-control-center
sudo nginx -t && sudo systemctl reload nginx
sudo install -m 0644 deployment/systemd/pinky-control-center.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pinky-control-center
systemctl status pinky-control-center --no-pager
```

실패 시 `journalctl -u pinky-control-center`와 `/var/log/pinky-control-center/server.log`에서 원인을 확인한다. 포트 충돌은 서버를 다른 로봇이나 mock endpoint로 자동 전환하지 않고 기동 실패로 남긴다.

## 4. 정지·재시작·복구

운영 중에는 UI의 전체 정지를 먼저 실행하고 두 로봇의 `CONFIRMED`를 확인한다. 응답하지 않은 로봇은 `UNCONFIRMED`로 유지하고 현장 절차를 따른다. 서버 재시작은 진행 중 임무를 재개하지 않는다.

```bash
sudo systemctl stop pinky-control-center
sudo systemctl start pinky-control-center
sudo systemctl restart pinky-control-center
```

SQLite 백업은 서비스 정지 후 복사하고, 복원 전 기존 DB를 날짜가 붙은 파일로 보존한다.

```bash
sudo systemctl stop pinky-control-center
sudo cp --preserve=all /var/lib/pinky-control-center/control.db \
  /var/lib/pinky-control-center/control.db.$(date -u +%Y%m%dT%H%M%SZ)
sudo systemctl start pinky-control-center
```

복구는 서비스 정지 → 검증된 백업을 `control.db`로 복사 → 소유자/권한 확인 → 서비스 시작 → 로그인·이력 조회 순서다. 백업을 찾지 못하면 빈 DB를 만들어 운용 이력을 잃지 말고 관리자에게 복구 실패를 보고한다.

## 5. ROS/Gazebo 인수 준비

T12 ROS 어댑터가 설치된 별도 workspace에서만 수행한다. `/etc/pinky-control-center/robots.ros.yaml`의 실제 주소·매핑을 먼저 확인하고, bridge 두 개는 서로 다른 domain과 포트를 사용한다. `pinky-control-center.service`는 API만 관리하며 rosbridge launch의 lifecycle은 별도 ROS supervisor/operator가 관리한다.

관제 PC에 rosbridge가 없다면 먼저 ROS 2 Jazzy 패키지를 설치한다. 설치 후 `ros2 pkg prefix rosbridge_server`가 경로를 출력해야 한다.

```bash
source /opt/ros/jazzy/setup.bash
sudo apt-get update
sudo apt-get install -y ros-jazzy-rosbridge-server
ros2 pkg prefix rosbridge_server
```

```bash
source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID=12
ros2 launch pinky_gz_sim launch_sim.launch.xml namespace:=robot_1 world_name:=pinky_factory.world
```

다른 터미널에서 `ROS_DOMAIN_ID=13`으로 `namespace:=robot_2`를 실행한다. 현재 `pinky_gz_sim/launch/launch_sim.launch.xml`에는 두 인스턴스의 x/y spawn 인자가 없고 기본 spawn 위치가 겹칠 수 있으므로, 별도 world 또는 launch 수정으로 위치를 분리하기 전에는 dual-robot Gazebo 인수를 실행하지 않는다. 이 제한은 acceptance report에서 NOT_RUN으로 남긴다. 그 다음 준비된 rosbridge-only launch를 실행한다.

```bash
source /opt/ros/jazzy/setup.bash
/usr/bin/python3 deployment/launch/control_center.launch.py
```

이 launch는 API나 Gazebo를 시작하지 않고 `robot_1 → ws://127.0.0.1:9090`(domain 12), `robot_2 → ws://127.0.0.1:9091`(domain 13)의 rosbridge만 시작한다. `/robot_1`과 `/robot_2`의 `odom`, `scan`, `/tf`·`/tf_static`를 각각 확인한다. compressed camera topic은 현재 raw camera 조사 결과만 있어 설정 후보가 미검증 상태이며, 실제 `CompressedImage` 발행 또는 변환 bridge를 확인하기 전에는 PASS로 기록하지 않는다. `map → <robot>/odom → <robot>/base_footprint` TF가 유효할 때만 다음 단계로 간다. control/follow 인터페이스, 단일 cmd_vel 중재, stop 래치·watchdog 계약이 없으면 실물 인수는 중단하고 NOT_RUN으로 기록한다.

검증 순서는 무이동 상태의 상태 수신 → 카메라 → 개별 정지 → 전체 정지 → 재연결이며, 무이동 검증을 통과하기 전에는 속도 제어를 열지 않는다. 결과와 명령·로그 증거는 [acceptance-report.md](acceptance-report.md)에 기록한다.
