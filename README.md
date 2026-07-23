# Academic Cluster

Academic Cluster 鏄竴涓浜庡紑鍙戦樁娈电殑瀛︽湳鏂囩尞宸ヤ綔娴佺郴缁燂紝鍩轰簬 FastAPI銆?
LangGraph銆丳ostgreSQL/pgvector銆丷edis 鍜?React/Vite 鍓嶇鏋勫缓銆傜郴缁熷洿缁曞崟涓」鐩绱?
璁烘枃銆佸垎鏋愯瘉鎹笌瑕嗙洊搴︺€佺敓鎴愮患杩般€佹墽琛屽悓琛岃瘎瀹★紝骞舵寔涔呭寲鏈€缁堢粨鏋溿€?

鐢熶骇娴佺▼鏄竴涓叿鏈夌増鏈寲鑺傜偣濂戠害鐨勫叚鑺傜偣 LangGraph 鐘舵€佹満锛岀洰鏍囨槸鎻愪緵鍙噸澶?
鎵ц銆佸熀浜?PostgreSQL 鐨?checkpoint 鎭㈠锛屼互鍙婂彲瀹¤鐨勮妭鐐圭骇鍙娴嬫€с€?

## 鑳藉姏姒傝

- 鎸夐」鐩绱€佸綊骞朵笌绠＄悊瀛︽湳璁烘枃銆?
- 鐢熸垚 embedding銆佽鐩栧害鍒嗘瀽銆佺煡璇嗗浘璋便€佽瘉鎹崱鐗囧拰鐮旂┒缂哄彛鍒嗘瀽銆?
- 鐢熸垚澶х翰銆佺患杩扮珷鑺傘€佸紩鐢ㄣ€佹憳瑕佸拰鏈€缁堢患杩般€?
- 鍦ㄧ粓缁撳墠鎵ц鍚岃璇勫锛屽苟杩涜鏈夌晫鐨勪慨璁㈡垨琛ュ厖妫€绱€?
- 閫氳繃 API 鎻愪緵濂戠害鍏冩暟鎹€佸喅绛栬褰曘€佸凡瀹¤宸ュ叿璋冪敤鍜?LLM 鐢ㄩ噺璁板綍銆?

## 澶氭櫤鑳戒綋娴佺▼

鍙湁浠ヤ笅鍏釜鍚嶇О鏄?LangGraph 鑺傜偣锛?code>supervisor</code>銆?
<code>research</code>銆?code>analysis</code>銆?code>writing</code>銆?
<code>peer_review</code> 涓?<code>finalize</code>銆俥mbedding銆佽仛绫汇€佺煡璇嗗浘璋便€?
璇佹嵁鍜岀己鍙ｅ垎鏋愬潎鏄?<code>analysis</code> 鑺傜偣鍐呴儴鎿嶄綔锛岃€屼笉鏄嫭绔嬬殑鍥捐妭鐐广€?

~~~mermaid
flowchart LR
    START["寮€濮?] --> S["supervisor"]
    S --> R["research"]
    S --> A["analysis"]
    S --> W["writing"]
    S --> P["peer_review"]
    S --> F["finalize"]
    R --> S
    A --> S
    W --> S
    P --> S
    F --> END["缁撴潫"]
~~~

Supervisor 涓嶈皟鐢?LLM 璺敱锛岃€屾槸鏍规嵁 <code>AgentState</code>銆侀噸璇曢绠椼€?
瑕嗙洊搴︾姸鎬佸拰璇勫鐘舵€佸喅瀹氫笅涓€闃舵銆傛墍鏈夐潪缁堢粨闃舵閮戒細杩斿洖 Supervisor銆傞粯璁ら绠椾负
姣忛樁娈典袱娆″皾璇曘€佷袱杞ˉ鍏呮绱㈠拰涓ゆ鍐欎綔淇銆?

瀹屾暣杩愯鏃惰璁¤ [鏋舵瀯璇存槑](docs/architecture.md)銆?

## 鎸佷箙鍖栦笌鎭㈠

姝ｅ紡 API/搴旂敤鍚姩璺緞浣跨敤 LangGraph 鐨?<code>AsyncPostgresSaver</code> 鍜?
PostgreSQL 杩炴帴姹犮€俢heckpoint 绾跨▼鍚屾椂浠?<code>project_id</code> 涓?
<code>execution_id</code> 闅旂锛?

~~~text
academic-cluster:agent:v1:{project_id}:{execution_id}
~~~

搴旂敤鍚姩瑕佹眰 PostgreSQL checkpointer 鍋ュ悍鍙敤锛屽苟鎸佹湁 PostgreSQL advisory lock銆?
鍚庣蹇呴』鍙繍琛屼竴涓繘绋嬪拰涓€涓?Uvicorn worker銆傛寔涔呭寲 checkpointer 鎴栧叾閿佷笉鍙敤鏃讹紝
杩愯鏃朵細鎷掔粷鎺ュ彈鏂扮殑 Agent 浠诲姟銆?

### 骞跺彂涓庤儗鍘?

褰撳墠閮ㄧ讲妯″瀷鏄?*鍗曚釜 checkpoint owner 鐨勬湁鐣屽苟鍙戞湇鍔?*锛屼笉鏄鍓湰 worker
闆嗙兢銆侫PI 鍦ㄦ寔涔呭寲 `pending` 鎵ц鍚庤繘鍏ヨ繘绋嬪唴 FIFO 璋冨害鍣細

- `AGENT_MAX_CONCURRENT_RUNS` 鎺у埗瀹為檯鎵ц涓殑椤圭洰鏁帮紱
- `AGENT_MAX_QUEUED_RUNS` 鎺у埗绛夊緟椤圭洰鏁帮紝婊¤浇鏃?`/agent/run` 涓庡吋瀹圭殑
  `/pipeline/{project_id}/start` 杩斿洖 HTTP `429`锛?
- `AGENT_MAX_ADMITTED_RUNS_PER_USER` 闃叉鍗曚竴鐢ㄦ埛鍗犳弧鍏ㄥ眬闃熷垪锛?
- 鍙栨秷鎺掗槦浠诲姟銆佸皻鏈緱鍒伴娆¤皟搴︾殑 task锛屾垨鍏抽棴鏈熼棿鏈敞鍐岀殑 task锛岄兘浼氬啓鍥?
  `interrupted`锛屼笉浼氱暀涓嬮樆濉炰笅涓€娆¤繍琛岀殑 `pending` 璁板綍锛?
- LLM 涓?embedding 鍒嗗埆缁忚繃鏄惧紡瀹归噺銆丗IFO 闃熷垪涓庣瓑寰?deadline锛涜繖浜涘閲忎笉浠?
  Provider RPM 鎺ㄥ銆侺iteLLM 缁х画璐熻矗渚涘簲鍟嗙骇 RPM/TPM銆乧ooldown 涓?failover锛?
- 姣忎釜椤圭洰鐨?KG/璇佹嵁/embedding fan-out 鍙楁瘡杩愯涓婇檺绾︽潫锛孨etworkX/Leiden
  鑱氱被杞叆宸ヤ綔绾跨▼锛孲SE 姣忚繛鎺ラ槦鍒楀拰姣忛」鐩繛鎺ユ暟鍧囨湁闄愬埗銆傛參 SSE 瀹㈡埛绔彧浼氭敹鍒?
  鏈€鏂颁簨浠讹紝杩囨湡浜嬩欢琚浛鎹㈣€屼笉浼氭棤闄愬崰鐢ㄥ唴瀛樸€?

榛樿鍊间紭鍏堜繚鎶ゆ暟鎹簱鍜?Provider锛? 涓椿鍔?Agent銆?2 涓帓闃?Agent銆佹瘡鐢ㄦ埛鏈€澶?
2 涓凡鍑嗗叆浠诲姟銆? 涓?LLM in-flight銆? 涓?embedding in-flight銆傝鍦ㄥ帇娴嬩笌
Provider 閰嶉楠岃瘉鍚庯紝閫氳繃 `.env` 涓殑 `AGENT_*`銆乣LLM_*`銆乣EMBEDDING_*` 鍜?
`SSE_*` 閰嶇疆璋冩暣锛涗笉瑕佷粎鍥犺緝楂?RPM 灏辨彁楂樺苟鍙戞Ы浣嶃€?

PostgreSQL 浠嶆槸 checkpoint 涓庡敮涓€娲昏穬鎵ц鐨勪簨瀹炴潵婧愶紝浣嗙洰鍓嶄笉鎻愪緵璺ㄥ疄渚?claim銆?
lease 鎴栬嚜鍔ㄩ噸鏂拌皟搴︺€傚洜姝ゅ鍔?Uvicorn worker銆佸鍣ㄥ壇鏈垨婊氬姩閮ㄧ讲涓殑骞惰
Agent worker 閮戒笉鍙楁敮鎸侊紱闇€瑕佹按骞虫墿灞曟椂锛屽簲鍏堝疄鐜版寔涔呭寲 job queue銆亀orker lease
鍜岃法瀹炰緥鐨?Provider 闄愰锛岃€屼笉鏄粫寮€ advisory lock銆?

<code>InMemorySaver</code> 浠嶇敤浜庣洿鎺ュ浘娴嬭瘯鍜岄殧绂荤殑纭畾鎬?E2E 娴嬭瘯銆傚畠涓嶆槸姝ｅ紡
API 鐨?checkpoint 璺緞锛岃繘绋嬮€€鍑哄悗涔熸棤娉曟仮澶嶇姸鎬併€?

## 鍓嶇疆鏉′欢

- Python 3.12 鎴栨洿楂樼増鏈€?
- 浣跨敤 [uv](https://docs.astral.sh/uv/) 鍒涘缓閿佸畾鐨勫紑鍙戠幆澧冦€?
- Docker Engine 涓?Docker Compose锛岀敤浜?PostgreSQL銆丷edis 鍜屽叏鏍堥儴缃层€?
- Node.js 涓?npm锛岀敤浜庡墠绔€侾romptfoo 闇€瑕?Node
  <code>^20.20.0 || >=22.22.0</code>銆?
- 鍙敤鐨?LLM Provider 涓?embedding Provider銆俥mbedding 妯″瀷蹇呴』杩斿洖鎭板ソ
  1024 涓湁闄愭暟鍊肩淮搴︺€?

## 閰嶇疆

鍒涘缓鏈湴鐜鏂囦欢锛?

~~~powershell
Copy-Item .env.example .env
~~~

~~~bash
cp .env.example .env
~~~

鍚姩瀹屾暣宸ヤ綔娴佸墠锛岃嚦灏戝簲鏇挎崲浠ヤ笅鍗犱綅鍊硷細

| 鑼冨洿 | 蹇呴渶閰嶇疆 |
| --- | --- |
| LLM | <code>LLM_MODEL</code>銆?code>LLM_BASE_URL</code>銆?code>LLM_API_KEY</code> |
| Embedding | <code>EMBEDDING_MODEL</code>銆?code>EMBEDDING_API_URL</code>銆?code>EMBEDDING_API_KEY</code> |
| PostgreSQL | 绠＄悊杩佺Щ璐﹀彿浣跨敤 <code>POSTGRES_USER</code>/<code>POSTGRES_PASSWORD</code>锛涘簲鐢ㄥ繀椤讳娇鐢ㄧ嫭绔嬬殑 <code>APP_POSTGRES_USER</code>/<code>APP_POSTGRES_PASSWORD</code> |
| Redis | <code>REDIS_HOST</code>銆?code>REDIS_PORT</code>銆?code>REDIS_PASSWORD</code> |
| 瀹夊叏閰嶇疆 | <code>JWT_SECRET_KEY</code>銆?code>PROVIDER_ENCRYPTION_KEY</code>銆?code>ALLOWED_HOSTS</code> |

<code>LLM_PROVIDERS_JSON</code> 涓?<code>EMBEDDING_PROVIDERS_JSON</code> 鍙€氳繃
LiteLLM 閰嶇疆澶氫釜 OpenAI-compatible endpoint锛屼篃鍙帴鍏ユ湰鍦扮殑
OpenAI-compatible 妯″瀷鏈嶅姟銆傝缃?<code>ADMIN_PASSWORD</code> 鍚庢墠浼氬垵濮嬪寲绠＄悊鍛橈紱
鍦ㄥ紑鍙戠幆澧冧腑鐣欑┖浼氳烦杩囩鐞嗗憳鍒涘缓銆?

鐢熶骇鐜璇疯缃?<code>APP_ENV=production</code>锛屼娇鐢ㄩ潪鍗犱綅鐨勫己瀵嗛挜锛屽苟鍦ㄩ噸鍚箣闂?
淇濇寔 <code>PROVIDER_ENCRYPTION_KEY</code> 涓嶅彉銆傚叕寮€娉ㄥ唽榛樿鍏抽棴锛涗粎鍦ㄦ槑纭渶瑕佹椂璁剧疆
<code>REGISTRATION_ENABLED=true</code>锛屽苟鍚屾椂閰嶇疆澶栭儴韬唤楠岃瘉鎴栭個璇锋祦绋嬨€?

## Docker 鍚姩

~~~powershell
Copy-Item .env.example .env
# 缂栬緫 .env锛氳嚦灏戣缃?POSTGRES_PASSWORD銆丄PP_POSTGRES_PASSWORD銆?
# REDIS_PASSWORD 鍜?Provider 鍑嵁锛涗袱涓?PostgreSQL 瀵嗙爜蹇呴』涓嶅悓銆?
# 褰?APP_ENV=production 鏃讹紝杩橀渶瑕佺敓浜х骇瀹夊叏閰嶇疆銆?
docker compose up -d --build
Invoke-WebRequest http://localhost:8000/health
~~~

~~~bash
cp .env.example .env
# 鎸変笂鏂囩紪杈?.env銆?
docker compose up -d --build
curl http://localhost:8000/health
~~~

榛樿鍦板潃锛?

| 鏈嶅姟 | 鍦板潃 |
| --- | --- |
| 鍓嶇 | <code>http://localhost:3000</code> |
| 鍚庣 API | <code>http://localhost:8000</code> |
| OpenAPI | <code>http://localhost:8000/docs</code>锛屼粎闈炵敓浜х幆澧冨惎鐢?|
| 鍋ュ悍妫€鏌?| <code>http://localhost:8000/health</code> |

Docker Compose 浼氬悜鍚庣瀹瑰櫒娉ㄥ叆 <code>POSTGRES_HOST=postgres</code> 鍜?
<code>POSTGRES_PORT=5432</code>锛屽苟鍦ㄥ簲鐢ㄥ惎鍔ㄥ墠鐢变竴娆℃€ц縼绉诲鍣ㄥ垱寤烘棤瓒呯骇鐢ㄦ埛銆?
鏃?<code>BYPASSRLS</code> 鏉冮檺鐨勫簲鐢ㄨ鑹插苟搴旂敤绉熸埛 RLS銆傛湰鍦板涓昏繘绋嬩娇鐢?
<code>.env</code> 涓殑 PostgreSQL 澶栭儴绔彛锛岄粯璁ゆ槸 <code>5433</code>銆?

## 鏈湴寮€鍙?

瀹夎閿佸畾鐨勫紑鍙戠幆澧冨苟鍚姩 PostgreSQL/Redis锛?

~~~powershell
uv sync --frozen --all-extras
docker compose up -d postgres redis
uv run academic-cluster --reload
~~~

~~~bash
uv sync --frozen --all-extras
docker compose up -d postgres redis
uv run academic-cluster --reload
~~~

鍦ㄧ浜屼釜缁堢鍚姩鍓嶇锛?

~~~powershell
Set-Location frontend
npm ci
npm run dev
~~~

~~~bash
cd frontend
npm ci
npm run dev
~~~

CLI 鏈夋剰鍥哄畾涓哄崟 worker銆備笉瑕佸鍔?Uvicorn worker 鏁伴噺锛屽洜涓?Agent 杩愯鏃朵緷璧?
鍗曚竴 PostgreSQL advisory-lock owner銆?

## 鑺傜偣濂戠害

姣忎釜鐢熶骇鍥捐妭鐐归兘鏈変竴涓?<code>NodeContract</code>锛屽０鏄庯細

- 绮剧‘鐨勩€佸甫鐗堟湰鐨勮緭鍏ュ拰杈撳嚭 Artifact 瀛楁銆?
- 鑷姩鐢熸垚鐨?Draft 2020-12 JSON Schema銆?
- 渚濊禆鎿嶄綔涓庡弬鏁扮粦瀹氥€?
- 鐢?<code>status</code> 閫夋嫨鐨勮緭鍑?variant銆?
- 宸插０鏄庣殑閿欒銆侀噸璇曡鍒欍€佸洖閫€瑙勫垯銆乫ixture 鍜岄獙鏀跺噯鍒欍€?

浠ヤ笅濂戠害鎺ュ彛闇€瑕佹櫘閫?API 璁よ瘉锛?

~~~text
GET /api/agent/contracts
GET /api/agent/contracts/{node_name}
~~~

鏈哄櫒鍙 bundle 浣嶄簬 <code>promptfoo/contracts/node-contracts.json</code>銆傚畠鍙兘浠?
鐢熶骇濂戠害鐢熸垚锛涜浣跨敤涓嬫枃妫€鏌ュ懡浠ゆ娴嬫紓绉汇€?

瀛楁绾ц鑼冭 [鑺傜偣濂戠害璇存槑](docs/node-contracts.md)銆?

### 褰撳墠濂戠害杈圭晫

褰撳墠濂戠害浼氭牎楠屽凡澹版槑鐨?Artifact 瀛楁銆佺増鏈€丣SON-compatible 绫诲瀷鍜岃緭鍑?variant銆?
瀹冨皻鏈疄鐜板鎵圭姸鎬併€丯08 寮曠敤鎵瑰噯銆丟07 瀹為獙鎵瑰噯銆佹樉寮?
<code>context_hash</code> 鎴?append-only 鍘嗗彶 Artifact 瀛樺偍绛夌瓥鐣ラ棬銆傚彧鏈夊皢杩欎簺
瑕佹眰瀹炵幇鍒拌繍琛屾椂鍚庯紝鎵嶈兘灏嗗叾澹版槑涓哄凡楠屾敹琛屼负銆?

## 鍙娴嬩笌璇勪及

### Langfuse

Langfuse 鏄彲閫変笖 fail-open 鐨勬梺璺娴嬪眰銆傚惎鐢ㄥ悗锛屽悓涓€涓?
<code>execution_id</code> 浼氫骇鐢熶竴涓?execution trace锛屽苟鍖呭惈瀹為檯鎵ц鑺傜偣鐨勫瓙 span銆?
榛樿璁板綍 Artifact 寮曠敤銆乻chema digest銆佽緭鍑?variant銆佺姸鎬佸拰鑰楁椂绛夊厓鏁版嵁锛屼笉鎹曡幏
鑺傜偣 payload銆?

~~~env
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_CAPTURE_NODE_IO=false
~~~

鍙湁鍦ㄩ殣绉佸鏌ュ厑璁告椂鎵嶈缃?<code>LANGFUSE_CAPTURE_NODE_IO=true</code>銆傚嵆渚垮惎鐢紝
鎹曡幏鍊间篃浼氱粡鍘嗚劚鏁忋€佹埅鏂拰宓屽娣卞害闄愬埗銆侺angfuse 鏄娴嬪眰锛屼笉鏄纭€ч棬绂佹垨
benchmark runner銆?

### Promptfoo

Promptfoo 褰撳墠鎵ц绂荤嚎銆佺‘瀹氭€х殑 **NodeContract 楠屾敹**銆傚畠鏍￠獙鍏釜
fixture/contract 缁勫悎锛屼笉璋冪敤 LLM銆佽鏂囨簮銆丳rovider 瀵嗛挜鎴栨暟鎹簱銆傚畠涓嶆槸
prompt 璐ㄩ噺 benchmark锛屼篃涓嶆槸瀹炴椂绔埌绔祴璇曘€?

~~~powershell
uv run python scripts/export_node_contracts.py --check
Set-Location promptfoo
$env:PROMPTFOO_PYTHON = (Resolve-Path ..\.venv\Scripts\python.exe).Path
promptfoo eval --config promptfooconfig.yaml --no-cache --no-write
~~~

~~~bash
uv run python scripts/export_node_contracts.py --check
cd promptfoo
PROMPTFOO_PYTHON="$(cd .. && pwd)/.venv/bin/python" \
  promptfoo eval --config promptfooconfig.yaml --no-cache --no-write
~~~

### Benchmark 鐘舵€?

椤圭洰灏氭湭鎻愪緵涓€绛夌殑鈥滈€愯妭鐐?+ 鍏ㄥ浘鈥?benchmark harness銆佺増鏈寲 benchmark 鏁版嵁闆嗐€?
璇勫垎鍣ㄦ垨鎶ュ憡 CLI銆傜洰鍓嶅凡鏈夌殑鏄‘瀹氭€у绾?fixture 鍜屼娇鐢?mock 鐨勫叏鍥?E2E 娴嬭瘯銆?

瑙勫垝涓殑 benchmark 鍒嗕负涓夊眰锛?

1. <code>offline-replay</code>锛氳剼鏈寲 LLM/tool 鍝嶅簲銆佺湡瀹炲浘璺敱鍜岀‘瀹氭€?CI 鏂█銆?
2. <code>local-llm</code>锛氬浐瀹?fixture銆乵ock 澶栭儴宸ュ叿涓庢湰鍦?
   OpenAI-compatible 妯″瀷銆?
3. <code>live</code>锛氭樉寮忓惎鐢ㄧ殑 Provider 璇勬祴锛屼娇鐢ㄩ殧绂荤殑鎸佷箙鍖栧拰 trace 鏁版嵁銆?

Promptfoo 鍙互鍦ㄨ鏋舵瀯涓瘎浼?prompt 鍥炲綊锛汱angfuse 鍙互璁板綍 benchmark trace锛?
浜岃€呴兘涓嶈兘鍙栦唬 benchmark harness銆?

## 娴嬭瘯涓庤川閲忓懡浠?

杩愯纭畾鎬?Python 娴嬭瘯锛?

~~~powershell
uv run pytest tests/unit/ -m "not integration and not live" -v --tb=short
~~~

鍙湁鍦ㄩ€氳繃 <code>ACADEMIC_CLUSTER_TEST_DATABASE_URL</code> 閰嶇疆浜嗘槑纭彲涓㈠純鐨?
娴嬭瘯鏁版嵁搴撳悗锛屾墠杩愯 PostgreSQL 闆嗘垚娴嬭瘯锛?

~~~powershell
uv run pytest tests/integration/ -m "integration and not live" -v --tb=short
~~~

杩愯闈欐€佹鏌ュ苟鏋勫缓 wheel锛?

~~~powershell
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/academic_cluster/
uv run bandit -r src/ -c pyproject.toml
uv run pip-audit
uv build --wheel
~~~

鍦?<code>frontend/</code> 鐩綍杩愯鍓嶇鏍￠獙锛?

~~~powershell
npm run lint
npm run type-check
npm run format:check
npm test
npm run build
~~~

纭畾鎬у浘 E2E 娴嬭瘯浣跨敤 <code>InMemorySaver</code> 鍜?fake provider銆傚畠鍙互楠岃瘉鍥捐涓猴紝
涓斾笉浼氭秷鑰?Provider 閰嶉鎴栦緷璧栧閮ㄦ湇鍔★紱瀹冧笉鑳借瘉鏄庣湡瀹炴ā鍨嬫垨 PostgreSQL 閮ㄧ讲銆?

## 椤圭洰缁撴瀯

~~~text
src/academic_cluster/
  agents/        LangGraph 鑺傜偣銆佸绾﹀拰 checkpoint 鐢熷懡鍛ㄦ湡
  api/           FastAPI 璺敱銆丼SE 涓庡簲鐢ㄧ敓鍛藉懆鏈?
  config/        閰嶇疆涓庡畨鍏ㄦ牎楠?
  services/      Provider銆佹寔涔呭寲銆佽娴嬩笌杩愯鏃剁鐞?
  tools/         宸插璁?Agent 宸ュ叿鍜岀‘瀹氭€у垎鏋愭搷浣?
frontend/         React 19 + Vite 搴旂敤
tests/            鍗曞厓娴嬭瘯涓?PostgreSQL 闆嗘垚娴嬭瘯
promptfoo/        绂荤嚎 NodeContract fixture 涓庢柇瑷€
docs/             鏋舵瀯鍜屽绾﹁鑼?
~~~

## 瀹夊叏璇存槑

- 涓嶈鎻愪氦 <code>.env</code>銆丳rovider 瀵嗛挜銆乼oken 鎴栫敓鎴愮殑 benchmark 瀵嗛挜銆?
- Refresh Token 鍙€氳繃 HttpOnly銆丼ameSite Cookie 浼犺緭锛涘墠绔笉寰楁妸 Access Token
  鎴?Refresh Token 鍐欏叆 localStorage銆?
- 椤圭洰鍜屾淳鐢熶骇鐗╅€氳繃缁勭粐鎴愬憳鍏崇郴銆佽姹傜骇绉熸埛涓婁笅鏂囧拰 PostgreSQL RLS 闅旂锛涚敓浜?
  搴旂敤璐﹀彿涓嶅緱浣跨敤 PostgreSQL 瓒呯骇鐢ㄦ埛鎴?<code>BYPASSRLS</code>銆?
- Provider 鍑虹珯鍦板潃榛樿鍙厑璁?HTTPS 鍏綉鍦板潃锛涙湰鍦扮缃?Provider 鍙兘鍦ㄩ潪鐢熶骇鐜
  閫氳繃鏄惧紡寮€鍏冲惎鐢紝涓?URL 鍙樺寲蹇呴』鍚屾杞崲 API Key銆?
- 闆嗘垚娴嬭瘯蹇呴』浣跨敤鍙涪寮冩暟鎹簱銆?
- 鏈湴 LLM benchmark 鏄湰鍦拌绠楋紝涓嶆槸纭畾鎬?replay锛涙瘮杈冩椂搴斾繚鐣欐ā鍨嬨€乸rompt銆?
  fixture 鍜岃緭鍑哄厓鏁版嵁銆?
- 涓嶈灏嗗綋鍓?Promptfoo 濂戠害楠屾敹缁撴灉瑙嗕綔瀹炴椂 LLM 璐ㄩ噺鎴栧畬鏁?E2E 姝ｇ‘鎬х殑璇佹嵁銆?

## 璁稿彲璇?

浠撳簱褰撳墠鏈寘鍚鍙瘉鏂囦欢銆傚湪瀵瑰鍙戝竷椤圭洰鎴栨帴鍙楀閮ㄨ础鐚墠锛岃琛ュ厖鏄庣‘鐨勮鍙瘉銆?
