"""Real PostgreSQL resolver regression using transaction-local shadow tables."""
import asyncio,ast,pathlib,json,os
from typing import Optional
from fastapi import HTTPException
from org_api import get_db_connection
async def main():
 source=pathlib.Path(os.environ.get('ENTITLEMENTS_SOURCE',str(pathlib.Path(__file__).resolve().parents[1]/'entitlements_api.py'))).read_text()
 tree=ast.parse(source);fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='_resolve_membership')
 scope={'Optional':Optional,'HTTPException':HTTPException};exec(compile(ast.Module(body=[fn],type_ignores=[]),'<actual-resolver>','exec'),scope);resolve=scope['_resolve_membership']
 c=await get_db_connection();tx=c.transaction();await tx.start()
 try:
  await c.execute('CREATE TEMP TABLE users(id text,zitadel_id text,email text) ON COMMIT DROP; CREATE TEMP TABLE organization_members(org_id text,user_id text,role text,is_default boolean DEFAULT false,joined_at timestamptz DEFAULT now()) ON COMMIT DROP')
  await c.execute("INSERT INTO users VALUES ('legacy-local','legacy-sub','same@example.test'),('foreign-local','foreign-sub','same@example.test'); INSERT INTO organization_members(org_id,user_id,role,is_default) VALUES ('demo-direct','direct-sub','member',true),('demo-legacy','legacy-local','owner',true),('foreign-org','foreign-local','member',true),('second-direct','direct-sub','member',false)")
  checks={}
  for name,sub,org,expected in [('direct-default','direct-sub',None,('demo-direct','member')),('direct-explicit','direct-sub','demo-direct',('demo-direct','member')),('legacy-default','legacy-sub',None,('demo-legacy','owner')),('legacy-explicit','legacy-sub','demo-legacy',('demo-legacy','owner')),('unknown','unknown-sub',None,(None,None)),('missing-sub',None,None,(None,None))]:
   assert await resolve({'sub':sub},c,org)==expected,name;checks[name]='PASS'
  for name,sub,org in [('direct-foreign','direct-sub','foreign-org'),('legacy-foreign-same-email','legacy-sub','foreign-org'),('unknown-explicit','unknown-sub','demo-direct')]:
   try:await resolve({'sub':sub},c,org)
   except HTTPException as e:assert e.status_code==403;checks[name]='PASS'
   else:raise AssertionError(name)
  print(json.dumps({'database':'real PostgreSQL; temporary shadow tables; transaction rolled back','checks':checks}))
 finally:await tx.rollback();await c.close()
if __name__ == '__main__': asyncio.run(main())
