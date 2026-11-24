-- Apply after 07_visitor_catalog_images.sql. The API uploads to VISITOR_IMAGE_BUCKET.
create function public.is_public_catalog_image_bucket(bucket_name text)
returns boolean
language sql stable security definer
set search_path = ''
as $$
  select exists (
    select 1 from storage.buckets as bucket
    where bucket.id = bucket_name and bucket.public
  );
$$;

revoke all on function public.is_public_catalog_image_bucket(text) from public;
grant execute on function public.is_public_catalog_image_bucket(text) to authenticated;

create policy "docent administrators can upload catalog images"
on storage.objects for insert to authenticated
with check (
  name ~ '^docent-catalog/[a-f0-9-]{36}/[a-f0-9]{64}\.(jpg|png)$'
  and (storage.foldername(name))[2] = (select auth.uid())::text
  and public.is_public_catalog_image_bucket(bucket_id)
  and exists (select 1 from public.admin_users where user_id = (select auth.uid()))
);
