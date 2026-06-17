from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]

def read(p): return (ROOT/p).read_text(encoding='utf-8')

def test_parser_multiple_ids_and_invalids():
    from app.plugins.tigrao_fsm.parsers import parse_user_ids
    p=parse_user_ids('123 456,789\n123 @user texto -5')
    assert p.valid == [123,456,789]
    assert p.invalid == ['@user','texto','-5']

@pytest.mark.asyncio
async def test_create_join_link_omits_member_limit():
    from app.plugins.tigrao_fsm.services import create_join_request_link
    class Bot:
        async def create_chat_invite_link(self, **kwargs):
            assert kwargs['creates_join_request'] is True
            assert 'member_limit' not in kwargs
            return kwargs
    await create_join_request_link(Bot(), -100, member_limit=1, name='x')

def test_storage_source_has_required_tables_and_columns():
    src=read('app/plugins/tigrao_fsm/storage.py')
    for token in ['tigrao_logs','tigrao_join_requests','tigrao_join_auto_accept','metadata_json','allowed_user_id','user_chat_id']:
        assert token in src

def test_telegram_py_not_altered_for_tigrao():
    assert 'tigrao_fsm' not in read('app/bot/telegram.py').lower()

def test_music_files_do_not_reference_tigrao():
    paths=['app/bot/radiofm.py','app/bot/tnow.py','app/bot/tly.py','app/bot/music_inline.py']
    paths += [str(p.relative_to(ROOT)) for p in (ROOT/'app/bot').glob('playing*.py')]
    paths += [str(p.relative_to(ROOT)) for p in (ROOT/'app/web_music').rglob('*.py')]
    for path in paths:
        assert 'tigrao_fsm' not in read(path).lower()
