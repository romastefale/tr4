# Fase 12D — X9 automático preservado

## Veredito

A Fase 12C estava correta em segurança, mas a documentação podia dar a impressão errada de que o X9 virou apenas passivo. Esta etapa corrige a leitura do produto:

- X9 automático/DDX continua agindo como antes quando há regra ativa.
- X9 contextual apenas alimenta o `/tmod` privado com grupo, mensagem e autor recentes.
- Grupo continua sem painel, sem botões e sem menu operacional.
- Web App continua como player.
- Ações humanas continuam em DM.

## Separação técnica

### X9 automático

Fluxo preservado em `app/equalizador/ddx.py`, chamado por `app/main.py` através de `equalizador_ddx_preprocess_update(...)`.

Esse fluxo pode:

- apagar mensagem automaticamente quando DDX hard bater;
- registrar ocorrência;
- avisar maestros/dono no privado;
- agendar remoção soft quando aplicável;
- consumir update antes dos handlers comuns quando a mensagem já foi removida.

### X9 contextual

Fluxo em `app/fsm_tigrao/x9.py` e `app/fsm_tigrao/context.py`.

Esse fluxo só:

- registra contexto limitado;
- respeita TTL e limite por grupo;
- não mostra nada no grupo;
- não substitui o DDX automático;
- não decide punição sozinho.

### FSM privado

Fluxo em `app/fsm_tigrao/router.py`.

Esse fluxo serve para decisão humana manual por DM:

- escolher grupo observado;
- escolher mensagem recente;
- confirmar ação;
- executar via backend com autorização.

## Regra final

```text
X9 automático age.
X9 contextual observa.
FSM privado decide.
Grupo não mostra menu.
Web App toca música.
```

## Arquivos tocados

- `app/main.py`
- `app/fsm_tigrao/x9.py`
- `app/fsm_tigrao/context.py`
- `tests/test_fsm_x9_automatico_preservado.py`
- `docs/FASE12D_X9_AUTOMATICO_PRESERVADO.md`
