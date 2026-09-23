# Tier-B Review Packet

## Sample 1

- Repo: `nocodb/nocodb`
- Raw Repo: `nocodb/nocodb`
- SHA: `8c5bd64990c21d39a14e281d33b47e41cea32bcb`
- Type: `refactor`
- Atomic Prior: `0.94732`
- Score: `31.473715`
- Utility: `90.954807`
- Files: `3`
- Hunks: `3`
- Changed Lines: `10`
- Roles: `source`
- Modules: `nc-gui-v2`
- Reasons: `pos:prefix_valid,pos:subject_compact,neg:body_compact,neg:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:file_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/nocodb/nocodb/commit/8c5bd64990c21d39a14e281d33b47e41cea32bcb

### Message

```text
refactor(gui-v2): expanded form ui corrections

- space between label and cell
- comment section take full height

Signed-off-by: Pranav C <pranavxc@gmail.com>
```

### Diff Excerpt

```diff
diff --git a/packages/nc-gui-v2/components/dashboard/TreeView.vue b/packages/nc-gui-v2/components/dashboard/TreeView.vue
index 931d18b861..2d3775cc60 100644
--- a/packages/nc-gui-v2/components/dashboard/TreeView.vue
+++ b/packages/nc-gui-v2/components/dashboard/TreeView.vue
@@ -29,8 +29,6 @@ const tablesById = $computed<Record<string, TableType>>(() =>
   }, {}),
 )
 
-const showTableList = ref(true)
-
 const tableCreateDlg = ref(false)
 
 let key = $ref(0)
diff --git a/packages/nc-gui-v2/components/smartsheet/expanded-form/Header.vue b/packages/nc-gui-v2/components/smartsheet/expanded-form/Header.vue
index d7d7f536ad..3c0f54621d 100644
--- a/packages/nc-gui-v2/components/smartsheet/expanded-form/Header.vue
+++ b/packages/nc-gui-v2/components/smartsheet/expanded-form/Header.vue
@@ -54,7 +54,7 @@ const iconColor = '#1890ff'
       v-if="isUIAllowed('rowComments')"
       class="cursor-pointer select-none"
       @click="commentsDrawer = !commentsDrawer"
-    />>
+    />
     <a-button class="!text" @click="emit('cancel')">
       <!-- Cancel -->
       {{ $t('general.cancel') }}
diff --git a/packages/nc-gui-v2/components/smartsheet/expanded-form/index.vue b/packages/nc-gui-v2/components/smartsheet/expanded-form/index.vue
index a98dfcb4b9..6d46b8d4ca 100644
--- a/packages/nc-gui-v2/components/smartsheet/expanded-form/index.vue
+++ b/packages/nc-gui-v2/components/smartsheet/expanded-form/index.vue
@@ -82,15 +82,15 @@ const isExpanded = useVModel(props, 'modelValue', emits)
 <template>
   <a-modal v-model:visible="isExpanded" :footer="null" width="min(90vw,1000px)" :body-style="{ padding: 0 }" :closable="false">
     <Header @cancel="isExpanded = false" />
-    <a-card class="!bg-gray-100 min-h-[70vh]">
-      <div class="flex h-full nc-form-wrapper items-stretch">
... [truncated]
```
