begin;

-- Apply after 09_admin_catalog_image_upload.sql.
drop policy if exists "docent administrators can upload catalog images" on storage.objects;
create policy "docent administrators can upload catalog images"
on storage.objects for insert to authenticated
with check (
  name ~ '^docent-catalog/[a-f0-9-]{36}/[a-f0-9]{64}\.(jpg|png|webp)$'
  and (storage.foldername(name))[2] = (select auth.uid())::text
  and public.is_public_catalog_image_bucket(bucket_id)
  and exists (select 1 from public.admin_users where user_id = (select auth.uid()))
);

commit;
