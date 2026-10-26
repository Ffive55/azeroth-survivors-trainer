import argparse,json
from engine import Trainer,restore_save

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['status','enable','set','restore','disable','restore-save']); p.add_argument('--class-id',type=int,default=8); p.add_argument('--value',type=int); p.add_argument('--backup')
    a=p.parse_args()
    if a.action=='restore-save': restore_save(a.backup)
    else:
        t=Trainer()
        try:
            t.connect()
            if a.action=='enable': t.enable()
            elif a.action=='set': t.set_available(a.class_id,a.value)
            elif a.action=='restore': t.restore_class(a.class_id)
            elif a.action=='disable': t.disable()
            print(json.dumps(t.status(allow_empty=True),ensure_ascii=False,indent=2))
        finally: t.close()
