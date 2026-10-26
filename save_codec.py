"""Native RSE1 save envelope: authenticated HMAC-SHA1 stream; standard library only."""
import base64,hashlib,hmac,os,struct
KEY=b"azeroth-survivors/save/v1/\x9cN'\xd1j\xf0\x13\xb8]\xe2q\x0c\xa96\xc4\x8f"
MAX_SIZE=4_000_000

def crypt(data,nonce):
    out=bytearray()
    for i in range(0,len(data),20):
        mask=hmac.new(KEY,b'ks'+nonce+struct.pack('<Q',i//20),hashlib.sha1).digest()
        out.extend(a^b for a,b in zip(data[i:i+20],mask))
    return bytes(out)

def decode(raw):
    if len(raw)>MAX_SIZE:raise ValueError('存档文件过大')
    if not raw.startswith(b'RSE1:'):raise ValueError('不是已验证的 RSE1 游戏存档')
    try:blob=base64.b64decode(raw[5:].strip(),validate=True)
    except Exception as e:raise ValueError('存档编码损坏') from e
    if len(blob)<36:raise ValueError('存档内容不完整')
    nonce,cipher,tag=blob[:16],blob[16:-20],blob[-20:]
    expected=hmac.new(KEY,b'tag'+nonce+cipher,hashlib.sha1).digest()
    if not hmac.compare_digest(tag,expected):raise ValueError('存档校验失败，拒绝修改')
    try:return crypt(cipher,nonce).decode('utf-8')
    except UnicodeDecodeError as e:raise ValueError('存档文本损坏') from e

def encode(text,nonce=None):
    raw=text.encode('utf-8')
    if len(raw)>MAX_SIZE//2:raise ValueError('存档文本过大')
    nonce=os.urandom(16) if nonce is None else nonce
    if len(nonce)!=16:raise ValueError('Invalid nonce')
    cipher=crypt(raw,nonce);tag=hmac.new(KEY,b'tag'+nonce+cipher,hashlib.sha1).digest()
    return b'RSE1:'+base64.b64encode(nonce+cipher+tag)
