## Escopo e Objetivo do Projeto

O objetivo é construir um agente autônomo de operações quantitativas em Python que integra ingestão de dados de mercado, geração de sinais estatísticos/IA, gestão de posição via gradiente linear, execução via MetaTrader 5 e validação anti-overfitting via Walk Forward Analysis, com métricas de performance (fator de lucro e fator de recuperação) como critério de aceite. Este documento serve como especificação técnica de alto nível para planejamento de sprints, definição de contratos de interface e priorização de entregas por um desenvolvedor Python senior.[^1]

## Princípios de Arquitetura

- Modularidade por domínio: cada estudo do material original (séries temporais, IA quant, indicadores, Markov, gradiente, MT5, WFA, métricas) deve virar um pacote Python isolado e testável, sem dependências circulares.[^1]
- Separação entre camada de dados, camada de decisão (sinais/estratégia) e camada de execução (broker/MT5), permitindo trocar o broker ou o modelo de IA sem reescrever o restante do agente.
- Configuração externa (YAML/`.env`) para parâmetros de risco, níveis de gradiente, credenciais MT5 e thresholds de indicadores — nada hardcoded no código de produção, alinhado à prática já usada pelo usuário em outros projetos com variáveis de ambiente.
- Todo componente que toca dinheiro real (envio de ordens) deve ter uma camada de simulação (dry-run) e um fluxo de confirmação/autorização antes de operar em conta real, dado o histórico do usuário com fluxos de confirmação seguros em outros agentes.

## Fase 1 — Fundação de Dados e Infraestrutura

Antes de qualquer lógica de sinal, é preciso um pipeline de dados confiável, pois todos os módulos de indicadores, Markov e IA dependem de séries temporais limpas e sincronizadas.[^1]

- Implementar `core/data_feed.py`: ingestão de OHLCV, resample multi-timeframe, tratamento de gaps e cálculo de retornos.
- Definir schema de persistência (SQLite/PostgreSQL, conforme stack já usada pelo usuário) para armazenar candles, sinais gerados e histórico de execuções, com SQLAlchemy.
- Criar suíte de testes unitários de qualidade de dados (candles duplicados, timestamps fora de ordem, valores nulos).
- Entregável da fase: pipeline de dados validado com testes automatizados e cobertura mínima definida pelo time.

## Fase 2 — Camada de Indicadores e Sinais

Esta fase constrói a "caixa de ferramentas" de sinais que alimentará tanto a estratégia baseada em regras quanto o modelo de IA.

- `indicators/quant_indicators.py`: registro plugável de indicadores (SMA, RSI, e extensível para novos).
- `indicators/obv_divergence.py`: detecção de divergência preço/OBV via inclinação de janelas móveis.
- `indicators/volatility.py`: ATR e volatilidade histórica anualizada, usados posteriormente para dimensionar stops e níveis do gradiente.[^1]
- `strategy/markov_chain.py`: classificação de regime de mercado (alta/baixa/lateral) e matriz de transição de probabilidades.[^1]
- Entregável da fase: cada indicador com testes unitários comparando saída contra valores de referência calculados manualmente ou via biblioteca consolidada (ex.: `ta-lib`, `pandas-ta`) como oráculo de validação.

## Fase 3 — Motor de Decisão (Lógica + IA)

Aqui se combina o motor de regras determinístico com o modelo de machine learning, permitindo modos de operação híbridos (regras puras, IA pura, ou ensemble).

- `core/logic_engine.py`: motor de regras (`Rule`/`LogicEngine`) para lógica condicional explícita e auditável.
- `ai_finance/ia_quant.py`: pipeline de features, treino e inferência (classificador de direção); versionar modelos treinados (ex.: `joblib`) com metadata de data de treino e métricas de validação.
- Definir contrato único de saída de sinal (ex.: `Signal(direction, confidence, source)`) para que regras e IA sejam intercambiáveis na camada de estratégia.
- Entregável da fase: backtest comparativo (regras vs. IA vs. ensemble) documentado com métricas de acurácia/precisão fora da amostra.

## Fase 4 — Gestão de Posição (Gradiente Linear)

O gradiente linear é o núcleo de gerenciamento de risco do agente: escalonamento de entradas com volumes iguais e saídas parciais por camada, com o preço médio convergindo matematicamente conforme o mercado avança.

- `strategy/linear_gradient.py`: implementar `LinearGradientManager` com suporte a direção (compra/venda), cálculo de preço médio ponderado e lógica de saída parcial por nível.
- Adicionar validação de invariantes: número de níveis, distância mínima entre níveis (ligada à volatilidade/ATR do Módulo de volatilidade), limite de exposição máxima por ativo.
- `agent_main.py`: orquestrador que integra sinal de entrada (Fase 3) ao gerenciador de gradiente, decidindo quando abrir, escalonar e encerrar posições.
- Entregável da fase: simulação completa em dados históricos mostrando preço médio, drawdown intermediário e resultado final por ciclo de gradiente.

## Fase 5 — Integração com MetaTrader 5

Esta fase conecta a lógica de decisão ao mundo real, usando a biblioteca `MetaTrader5` para leitura de mercado e envio de ordens, replicando as funções nativas da plataforma (EAs, ordens, times frames).

- `platform/mt5_connector.py`: encapsular `initialize`, `copy_rates_from_pos` e `order_send`, com tratamento de erro e reconexão automática.
- Implementar modo dry-run (log de ordens simuladas) como padrão, exigindo flag explícita para habilitar execução real — ponto crítico de segurança operacional.
- Adicionar camada de idempotência/magic number para evitar duplicidade de ordens em caso de reprocessamento.
- Entregável da fase: teste de integração em conta demo, cobrindo abertura, escalonamento e fechamento de posição fim a fim.

## Fase 6 — Otimização e Validação (Anti-Overfitting)

Antes de qualquer promoção para conta real, os parâmetros da estratégia (níveis de gradiente, thresholds de indicadores, hiperparâmetros de IA) precisam ser validados fora da amostra usando Walk Forward Analysis, evitando o erro comum de otimizar no histórico completo e assumir que o resultado se repetirá.

- `optimization/walk_forward.py`: implementar janelas deslizantes de in-sample/out-of-sample, com função de otimização (grid search ou bayesiana) e função de backtest injetáveis.
- `optimization/performance_metrics.py`: calcular fator de lucro e fator de recuperação por janela, com referência de qualidade (fator de lucro ≥ 1.45–1.5) para aprovação automática de um parametro set.
- Adicionar `consistency_score` para quantificar a diferença de performance entre in-sample e out-of-sample; usar como gate automático de CI antes de permitir deploy de novos parâmetros.
- Entregável da fase: relatório de WFA reproduzível (notebook ou script) versionado junto ao histórico de parâmetros aprovados.

## Fase 7 — Orquestração, Observabilidade e Deploy

- Consolidar `agent_main.py` como orquestrador único, com ciclo de vida claro: coleta de dados → sinal → gestão de posição → execução → log de métricas.
- Instrumentar logging estruturado (JSON) e métricas de runtime (latência de ciclo, número de ordens, erros de conexão MT5), reaproveitando padrões de observabilidade já usados pelo usuário em outros agentes.
- Expor painel de acompanhamento (Streamlit) com equity curve, posições abertas, divergências detectadas e métricas de fator de lucro/recuperação em tempo real, dado o padrão de UI já adotado pelo usuário em outros projetos.
- Definir estratégia de deploy (cron/serviço systemd, container, ou cloud) com variáveis de ambiente para credenciais MT5 e parâmetros de risco, sem segredos versionados no repositório.

## Backlog Técnico Priorizado

| Prioridade | Item | Módulo | Critério de aceite |
|---|---|---|---|
| P0 | Pipeline de dados validado | `core/data_feed.py` | Testes de integridade passando, sem gaps não tratados |
| P0 | Conector MT5 com dry-run | `platform/mt5_connector.py` | Ordens simuladas logadas corretamente em conta demo |
| P1 | Gestão de gradiente linear | `strategy/linear_gradient.py` | Preço médio calculado corretamente contra casos de teste manuais |
| P1 | Motor de regras + sinal IA | `core/logic_engine.py`, `ai_finance/ia_quant.py` | Contrato de sinal único, backtest comparativo documentado |
| P1 | Indicadores plugáveis + OBV divergência | `indicators/` | Cobertura de testes ≥ 80% no pacote |
| P2 | Cadeia de Markov para regime de mercado | `strategy/markov_chain.py` | Matriz de transição validada contra sequência conhecida[^1] |
| P2 | Walk Forward Analysis + métricas | `optimization/` | Fator de lucro out-of-sample ≥ 1.45 nas janelas aprovadas |
| P3 | Painel Streamlit e observabilidade | UI/monitoring | Dashboard exibindo equity curve e posições em tempo real |

## Riscos Técnicos e Pontos de Atenção

- Overfitting de parâmetros é o maior risco silencioso: nenhum parâmetro deve ir para conta real sem passar pelo gate de WFA e consistency score.
- Divergência entre backtest e execução real no MT5 (slippage, latência, requotes) deve ser monitorada desde a Fase 5 com métricas de "slippage médio" versus o esperado no backtest.
- O gradiente linear aumenta exposição em movimentos contrários; é obrigatório definir limite máximo de drawdown por ativo e circuito de parada automática (kill switch) antes de qualquer deploy em conta real.
- Modelos de IA devem ser retreinados e revalidados periodicamente (ex.: mensalmente) para evitar drift de regime de mercado não capturado pela Cadeia de Markov ou pelas features estáticas.

## Ordem de Entrega Recomendada para o Desenvolvedor

1. Fundação de dados e infraestrutura (Fase 1).
2. Indicadores e sinais determinísticos (Fase 2).
3. Motor de decisão híbrido regras + IA (Fase 3).
4. Gestão de posição via gradiente linear em ambiente simulado (Fase 4).
5. Integração MT5 em conta demo com dry-run obrigatório (Fase 5).
6. Validação estatística via WFA e métricas de performance como gate de promoção (Fase 6).
7. Orquestração final, observabilidade e deploy controlado (Fase 7).

Essa sequência garante que cada camada seja validada isoladamente antes de ser conectada à execução real, reduzindo risco de perdas por falhas de integração ou parâmetros não validados.

---

## References

1. [ANALISE-QUANTITATIVA-ESTUDOS.txt](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/904711381/a8160e94-990b-47f8-9619-e0bced515a64/ANALISE-QUANTITATIVA-ESTUDOS.txt?AWSAccessKeyId=ASIA2F3EMEYEUYJR2D5L&Signature=waDoPrWFhMfjpjRXUsnUALAo%2BVQ%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELL%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIHgGPji7I7F27xsVkRypoQIXBVU1pvTnZnexDkU5Bhx2AiBDozfQDtWTMryBpdt7KOCeCO%2Fqo9kcDW42RPT9BPBG5SrzBAh6EAEaDDY5OTc1MzMwOTcwNSIMqAuwHV2G2KtVpVpTKtAE5kbcZwlUH5%2FHUo7QxzLo7dhvItPQKNSo4uu14RuhTbzzrk0bOTmPlf%2F7wGdvWgZ0cdzeVf9gIHg6P4w2Mx%2Bk7yY5ca5SVTCq8jDj2xK2Ne8m7MznjO2RB7Xb1uFN7qcfU2BYY%2FfqAC0CI6AJoJmzEPjm12emsF3xfFKK1eNDw2X4mnTW6Q%2Fl9MXgk2Al3XrSQZrk%2FATyylkyj05vxZCwlWjZg4RFBxATrQOfuwjHuF84eLyt500SqO5dJt0HtQCboqIEaSecIPGLr2JtX6BNYv5dXewjji0nYt2IDfxq8Vqx0SSFEMB69ILf4bFA1I4JWi5Hsh1jdhirG8VznLx22s7cGFvax8F%2FkIBmJMl86fmtaJRA8Qb8yV27R4UFM0O4C2o2RBiXNv2GtX8DCHP10QeGS46idlkB%2Bktlkn1%2BdseyLxJQfxPjJ5OAzQxdA7%2FeCmXSU8%2FlM7oQRIZMc9OujrHgCetKvJVjFM3dOZZgJXWNiqAvtSjNTuI28RzDtji%2BnH2ULCBQjdlNKWMHr9JyGiQDwky4fSB7zF290z5AWYN9fe%2BHsfIVArtzO8WYxWbmEBvLiprcFtiHzkzVBaam8av1fGL%2FpRcsqNARmNhGY88geUU%2BHSKOx%2BScBIqIOYfC8vx0EbbIkEnJH%2Fw1s%2BTLgRFqGvxqubTjLcMWtwdmHcI2x8KkUakoXmsupEUZtiEHUVc2xTklkT7JuWckP4xg8EqHeSmcXXfHxV%2FO41oAx8swBUUB8OvtyGICabUBoxPZiu60svPOYRn5L6UMl8YZVzCeiYjVBjqZAdjqZkNECKOL4IJZCvQtwZNOVQ4zoZTQ9pn9XKoiaKBxpJ4T%2Biy6sUm0AUxtti1T2bJM3HxyhYuXgUM0DCrr3urKwUYLsVVP1PcatvojWv%2FdHp%2BEr6WJffBzKkJPCRJ68%2BojeOP15ryhV8NxsMWYRTdju%2BEHkdqicIxEPu19MVDbSvmk5oCH0BSdibq4Il4gC0fE0D%2BURkbYPw%3D%3D&Expires=1789006449) - ANALISE QUANTITATIVA

Séries Temporais          : https://www.youtube.com/playlist?list=PLNJN8eyDz...

