# Fase 54.1 — Equalizador em janelas

Esta etapa reorganiza a navegação do Mini App sem adicionar novas chamadas críticas ao Telegram.

## Escopo aplicado

- Cria navegação por janelas internas: Início, Perfil do grupo, Mensagens, Pessoas, Convites, Tópicos, Transmissão, Diagnóstico, Histórico e Configuração.
- Separa personalização textual do grupo em **Perfil do grupo**.
- Separa mensagens e fixação em **Mensagens**.
- Separa membros, administradores, pedidos de entrada e canais remetentes em **Pessoas**.
- Separa convites em **Convites**.
- Separa tópicos/fóruns em **Tópicos**.
- Mantém transmissão e modo silêncio em janela própria, visível só para administrador principal.
- Reforça contraste visual: fundo cinza mais escuro, cards com borda mais evidente, texto branco mais legível e campos com maior separação.
- Remove da instrução principal da interface o convite para uso de ID numérico; quando necessário, o backend ainda pode resolver internamente sem expor ID na tela.

## Fora do escopo desta etapa

- Trocar foto do grupo.
- Remover foto do grupo.
- Criar novas rotas de upload multipart.
- Normalização completa de 400/403/409/429.

Esses itens ficam para as próximas etapas, para evitar regressão em ações já existentes.

## Validação local

- `python -m compileall -q app scripts tests`
- `PYTHONPATH=. pytest -q`
- `PYTHONPATH=. python scripts/equalizador_release_check.py`
