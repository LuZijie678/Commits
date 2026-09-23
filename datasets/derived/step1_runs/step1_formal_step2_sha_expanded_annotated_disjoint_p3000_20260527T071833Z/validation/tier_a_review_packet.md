# Tier-A Review Packet

## Sample 1

- Repo: `aidenybai/million`
- Raw Repo: `aidenybai/million`
- SHA: `c7b35cf96c833a638994c7fe99e320e8eed839aa`
- Type: `feat`
- Atomic Prior: `1.0`
- Score: `53.429229`
- Utility: `85.544129`
- Files: `1`
- Hunks: `2`
- Changed Lines: `9`
- Roles: `source`
- Modules: `patch.ts`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,neg:commit_type_signal`
- Commit URL: https://github.com/aidenybai/million/commit/c7b35cf96c833a638994c7fe99e320e8eed839aa

### Message

```text
feat(patch): pass important information to effect functions
```

### Diff Excerpt

```diff
diff --git a/src/patch.ts b/src/patch.ts
index 68f4c20e..f458456c 100644
--- a/src/patch.ts
+++ b/src/patch.ts
@@ -197,7 +197,12 @@ export const init =
   (
     customPatchProps: typeof patchProps = patchProps,
     customPatchChildren: typeof patchChildren = patchChildren,
-    ...effects: (() => void)[]
+    ...effects: ((
+      el: HTMLElement | Text,
+      newVNode: VNode,
+      prevVNode: VNode | undefined,
+      workStack: (() => void)[],
+    ) => void)[]
   ) =>
   (
     el: HTMLElement | Text,
@@ -273,7 +278,7 @@ export const init =
 
         if (effects.length > 0) {
           for (let i = 0; i < effects.length; ++i) {
-            effects[i]();
+            effects[i](el, newVNode, oldVNode, workStack);
           }
         }
       }
```

## Sample 2

- Repo: `callstack/react-native-paper`
- Raw Repo: `callstack/react-native-paper`
- SHA: `860a5348df7e10af850641eb32c572860977cec2`
- Type: `fix`
- Atomic Prior: `1.0`
- Score: `60.089534`
- Utility: `91.28837`
- Files: `7`
- Hunks: `8`
- Changed Lines: `32`
- Roles: `source`
- Modules: `components`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:commit_type_signal,pos:file_scope_signal`
- Commit URL: https://github.com/callstack/react-native-paper/commit/860a5348df7e10af850641eb32c572860977cec2

### Message

```text
fix: use color prop instead of style in Icon. closes #291, #294
```

### Diff Excerpt

```diff
diff --git a/src/components/Checkbox.ios.js b/src/components/Checkbox.ios.js
index 359e569b0..1aa4bbc79 100644
--- a/src/components/Checkbox.ios.js
+++ b/src/components/Checkbox.ios.js
@@ -67,7 +67,8 @@ class Checkbox extends React.Component<Props> {
               allowFontScaling={false}
               name={checked && 'done'}
               size={24}
-              style={[styles.icon, { color: checkedColor }]}
+              color={checkedColor}
+              style={styles.icon}
             />
           )}
         </View>
diff --git a/src/components/Checkbox.js b/src/components/Checkbox.js
index 742e4fc10..d77c87be9 100644
--- a/src/components/Checkbox.js
+++ b/src/components/Checkbox.js
@@ -139,7 +139,8 @@ class Checkbox extends React.Component<Props, State> {
             allowFontScaling={false}
             name={checked ? 'check-box' : 'check-box-outline-blank'}
             size={24}
-            style={[styles.icon, { color: checkboxColor }]}
+            color={checkboxColor}
+            style={styles.icon}
           />
           <View style={[StyleSheet.absoluteFill, styles.fillContainer]}>
             <Animated.View
diff --git a/src/components/FAB.js b/src/components/FAB.js
index 23124effd..7cd2d6346 100644
--- a/src/components/FAB.js
+++ b/src/components/FAB.js
@@ -91,7 +91,7 @@ const FAB = (props: Props) => {
         style={[styles.content, small ? styles.small : styles.standard]}
       >
         <View>
... [truncated]
```

## Sample 3

- Repo: `camunda/zeebe`
- Raw Repo: `camunda/zeebe`
- SHA: `10a531fa098d61682d295168c1a32265143c41b0`
- Type: `feat`
- Atomic Prior: `1.0`
- Score: `49.145936`
- Utility: `79.519866`
- Files: `5`
- Hunks: `10`
- Changed Lines: `73`
- Roles: `source`
- Modules: `topology`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:hunk_scope_signal,neg:commit_type_signal,pos:file_scope_signal`
- Commit URL: https://github.com/camunda/zeebe/commit/10a531fa098d61682d295168c1a32265143c41b0

### Message

```text
feat(topology): handle get topology query in broker
```

### Diff Excerpt

```diff
diff --git a/topology/src/main/java/io/camunda/zeebe/topology/api/TopologyManagementApi.java b/topology/src/main/java/io/camunda/zeebe/topology/api/TopologyManagementApi.java
index f8ce85890a9..c8b6e24d46d 100644
--- a/topology/src/main/java/io/camunda/zeebe/topology/api/TopologyManagementApi.java
+++ b/topology/src/main/java/io/camunda/zeebe/topology/api/TopologyManagementApi.java
@@ -14,6 +14,7 @@ import io.camunda.zeebe.topology.api.TopologyManagementRequest.LeavePartitionReq
 import io.camunda.zeebe.topology.api.TopologyManagementRequest.ReassignPartitionsRequest;
 import io.camunda.zeebe.topology.api.TopologyManagementRequest.RemoveMembersRequest;
 import io.camunda.zeebe.topology.api.TopologyManagementRequest.ScaleRequest;
+import io.camunda.zeebe.topology.state.ClusterTopology;
 
 /** Defines the API for the topology management requests. */
 public interface TopologyManagementApi {
@@ -30,4 +31,6 @@ public interface TopologyManagementApi {
       ReassignPartitionsRequest reassignPartitionsRequest);
 
   ActorFuture<TopologyChangeResponse> scaleMembers(ScaleRequest scaleRequest);
+
+  ActorFuture<ClusterTopology> getTopology();
 }
diff --git a/topology/src/main/java/io/camunda/zeebe/topology/api/TopologyManagementRequestSender.java b/topology/src/main/java/io/camunda/zeebe/topology/api/TopologyManagementRequestSender.java
index 0bc762e60c6..77a3bea93b3 100644
--- a/topology/src/main/java/io/camunda/zeebe/topology/api/TopologyManagementRequestSender.java
+++ b/topology/src/main/java/io/camunda/zeebe/topology/api/TopologyManagementRequestSender.java
@@ -16,8 +16,10 @@ import io.camunda.zeebe.topology.api.TopologyManagementRequest.ReassignPartition
 import io.camunda.zeebe.topology.api.TopologyManagementRequest.RemoveMembersRequest;
 import io.camunda.zeebe.topology.api.TopologyManagementRequest.ScaleRequest;
 import io.camunda.zeebe.topology.serializer.TopologyRequestsSerializer;
+import io.camunda.zeebe.topology.state.ClusterTopology;
 import java.time.Duration;
 import java.util.concurrent.CompletableFuture;
+import java.util.function.Function;
 
 /** Forwards all requests to the coordinator. */
 public final class TopologyManagementRequestSender {
@@ -99,4 +101,14 @@ public final class TopologyManagementRequestSender {
         coordinator,
... [truncated]
```

## Sample 4

- Repo: `camunda/zeebe`
- Raw Repo: `camunda/zeebe`
- SHA: `b5a97bcb40fcd2daadf7ee7c0702b1d0d08132cc`
- Type: `refactor`
- Atomic Prior: `1.0`
- Score: `59.300378`
- Utility: `91.935199`
- Files: `1`
- Hunks: `1`
- Changed Lines: `3`
- Roles: `source`
- Modules: `transport`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/camunda/zeebe/commit/b5a97bcb40fcd2daadf7ee7c0702b1d0d08132cc

### Message

```text
refactor(transport): remove invalid comment
```

### Diff Excerpt

```diff
diff --git a/transport/src/main/java/io/camunda/zeebe/transport/stream/impl/ClientStreamRegistry.java b/transport/src/main/java/io/camunda/zeebe/transport/stream/impl/ClientStreamRegistry.java
index 7bc5847b7b7..0d10621b904 100644
--- a/transport/src/main/java/io/camunda/zeebe/transport/stream/impl/ClientStreamRegistry.java
+++ b/transport/src/main/java/io/camunda/zeebe/transport/stream/impl/ClientStreamRegistry.java
@@ -20,9 +20,6 @@ import org.agrona.DirectBuffer;
 
 /** A registry to keeps tracks of all open streams. */
 final class ClientStreamRegistry<M extends BufferWriter> {
-
-  // This class is currently a very simple wrapper around a map. When we aggregate multiple streams
-  // into one stream, we may have to keep track of them also here.
   private final Map<UUID, ClientStream<M>> clientStreams = new HashMap<>();
   private final Map<UUID, AggregatedClientStream<M>> serverStreams = new HashMap<>();
```

## Sample 5

- Repo: `camunda/zeebe`
- Raw Repo: `camunda/zeebe`
- SHA: `f5169f05880ae05cc2047cf52a4ba4699f0d591d`
- Type: `test`
- Atomic Prior: `1.0`
- Score: `60.375698`
- Utility: `93.036742`
- Files: `2`
- Hunks: `3`
- Changed Lines: `41`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/camunda/zeebe/commit/f5169f05880ae05cc2047cf52a4ba4699f0d591d

### Message

```text
test(broker): verify that query api can be enabled
```

### Diff Excerpt

```diff
diff --git a/broker/src/test/java/io/camunda/zeebe/broker/system/configuration/BrokerCfgTest.java b/broker/src/test/java/io/camunda/zeebe/broker/system/configuration/BrokerCfgTest.java
index afdfe75ed33..810d9597ba5 100644
--- a/broker/src/test/java/io/camunda/zeebe/broker/system/configuration/BrokerCfgTest.java
+++ b/broker/src/test/java/io/camunda/zeebe/broker/system/configuration/BrokerCfgTest.java
@@ -65,6 +65,8 @@ public final class BrokerCfgTest {
       "zeebe.broker.experimental.disableExplicitRaftFlush";
   private static final String ZEEBE_BROKER_EXPERIMENTAL_ENABLEPRIORITYELECTION =
       "zeebe.broker.experimental.enablePriorityElection";
+  private static final String ZEEBE_BROKER_EXPERIMENTAL_QUERYAPI_ENABLED =
+      "zeebe.broker.experimental.queryapi.enabled";
   private static final String ZEEBE_BROKER_DATA_DIRECTORY = "zeebe.broker.data.directory";
 
   private static final String ZEEBE_BROKER_NETWORK_HOST = "zeebe.broker.network.host";
@@ -513,6 +515,43 @@ public final class BrokerCfgTest {
     assertThat(experimentalCfg.isEnablePriorityElection()).isTrue();
   }
 
+  @Test
+  public void shouldDisableQueryApiByDefault() {
+    // given
+    final BrokerCfg cfg = TestConfigReader.readConfig("cluster-cfg", environment);
+
+    // when
+    final ExperimentalCfg experimentalCfg = cfg.getExperimental();
+
+    // then
+    assertThat(experimentalCfg.getQueryApi().isEnabled()).isFalse();
+  }
+
+  @Test
+  public void shouldSetEnableQueryApiFromConfig() {
+    // given
+    final BrokerCfg cfg = TestConfigReader.readConfig("experimental-cfg", environment);
+
+    // when
+    final ExperimentalCfg experimentalCfg = cfg.getExperimental();
... [truncated]
```

## Sample 6

- Repo: `camunda/zeebe`
- Raw Repo: `camunda/zeebe`
- SHA: `ef6808a7345dee1b22137b7733d2c7375e488692`
- Type: `test`
- Atomic Prior: `1.0`
- Score: `42.659804`
- Utility: `91.457359`
- Files: `2`
- Hunks: `7`
- Changed Lines: `62`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,pos:subject_compact,neg:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/camunda/zeebe/commit/ef6808a7345dee1b22137b7733d2c7375e488692

### Message

```text
test(os-exporter): verify ISM policy is updated when it exists

Adds an IT that creates an ISM policy using the configuration, but with
a custom minimum age.
After exporting a record the exporter should update this policy. We can
verify this by asserting if the minimum age changed from the 100d to the
 value of the configuration.
```

### Diff Excerpt

```diff
diff --git a/exporters/opensearch-exporter/src/test/java/io/camunda/zeebe/exporter/opensearch/OpensearchExporterIT.java b/exporters/opensearch-exporter/src/test/java/io/camunda/zeebe/exporter/opensearch/OpensearchExporterIT.java
index 5495beab604..82169d9d33e 100644
--- a/exporters/opensearch-exporter/src/test/java/io/camunda/zeebe/exporter/opensearch/OpensearchExporterIT.java
+++ b/exporters/opensearch-exporter/src/test/java/io/camunda/zeebe/exporter/opensearch/OpensearchExporterIT.java
@@ -197,7 +197,7 @@ final class OpensearchExporterIT {
   }
 
   @Test
-  void shouldPutIndexStateManagementPolicy() {
+  void shouldCreateIndexStateManagementPolicy() {
     // given
     final var record = factory.generateRecord();
 
@@ -238,4 +238,22 @@ final class OpensearchExporterIT {
         .containsOnly(config.index.prefix + "*");
     assertThat(ismTemplate.priority()).as("Has low priority").isEqualTo(1);
   }
+
+  @Test
+  void shouldUpdateIndexStateManagementPolicy() {
+    // given - Make sure we create the policy before the exporter does
+    final var initialMinimumAge = "100d";
+    assertThat(initialMinimumAge).isNotEqualTo(config.retention.getMinimumAge());
+    testClient.putIndexStateManagementPolicy(initialMinimumAge);
+    final var record = factory.generateRecord();
+
+    // when - export a single record to enforce creating the policy
+    exporter.export(record);
+
+    // then
+    final var updatedPolicy = testClient.getIndexStateManagementPolicy().policy();
+    final String updatedMinimumAge =
+        updatedPolicy.states().getFirst().transitions().getFirst().conditions().minIndexAge();
+    assertThat(updatedMinimumAge).isEqualTo(config.retention.getMinimumAge());
+  }
 }
... [truncated]
```

## Sample 7

- Repo: `camunda/zeebe`
- Raw Repo: `camunda/zeebe`
- SHA: `c83bb6e4a1d61a5919ba18efacf9ffb73b36e955`
- Type: `test`
- Atomic Prior: `1.0`
- Score: `30.665601`
- Utility: `93.43898`
- Files: `1`
- Hunks: `1`
- Changed Lines: `1`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,neg:subject_compact,neg:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/camunda/zeebe/commit/c83bb6e4a1d61a5919ba18efacf9ffb73b36e955

### Message

```text
test: ignore test

We need to refactor this tests soon.
```

### Diff Excerpt

```diff
diff --git a/engine/src/test/java/io/camunda/zeebe/engine/processing/streamprocessor/StreamProcessorHealthTest.java b/engine/src/test/java/io/camunda/zeebe/engine/processing/streamprocessor/StreamProcessorHealthTest.java
index 35ad767a22e..afdf825c06b 100644
--- a/engine/src/test/java/io/camunda/zeebe/engine/processing/streamprocessor/StreamProcessorHealthTest.java
+++ b/engine/src/test/java/io/camunda/zeebe/engine/processing/streamprocessor/StreamProcessorHealthTest.java
@@ -80,6 +80,7 @@ public class StreamProcessorHealthTest {
   }
 
   @Test
+  @Ignore("They don't work anymore like they were intended since the writing of records changed")
   public void shouldMarkUnhealthyWhenExceptionErrorHandlingInTransaction() {
     // given
     shouldProcessingThrowException.set(true);
```

## Sample 8

- Repo: `crimx/ext-saladict`
- Raw Repo: `crimx/ext-saladict`
- SHA: `074b165fb393f25b6dd23009c96109828fa71aed`
- Type: `refactor`
- Atomic Prior: `1.0`
- Score: `59.276259`
- Utility: `91.900222`
- Files: `1`
- Hunks: `2`
- Changed Lines: `20`
- Roles: `source`
- Modules: `_helpers`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/crimx/ext-saladict/commit/074b165fb393f25b6dd23009c96109828fa71aed

### Message

```text
refactor: add dicts styles on internal page
```

### Diff Excerpt

```diff
diff --git a/src/_helpers/injectSaladictInternal.ts b/src/_helpers/injectSaladictInternal.ts
index 8cc7034b..ed71118a 100644
--- a/src/_helpers/injectSaladictInternal.ts
+++ b/src/_helpers/injectSaladictInternal.ts
@@ -1,3 +1,5 @@
+import { createActiveProfileStream } from './profile-manager'
+
 export function injectSaladictInternal (noInjectContentCSS?: boolean) {
   if (process.env.NODE_ENV === 'development') {
     return
@@ -27,4 +29,22 @@ export function injectSaladictInternal (noInjectContentCSS?: boolean) {
     }
     document.head.appendChild($stylePanel)
   }
+
+  const selectedDicts = new Set()
+  createActiveProfileStream().subscribe(profile => {
+    profile.dicts.selected.forEach(dict => {
+      if (!selectedDicts.has(dict)) {
+        const $styleDict = document.createElement('link')
+        $styleDict.href = `./dicts/internal/${dict}.css`
+        $styleDict.rel = 'stylesheet'
+        if (document.head) {
+          document.head.appendChild($styleDict)
+        } else {
+          document.body.appendChild($styleDict)
+        }
+
+        selectedDicts.add(dict)
+      }
+    })
+  })
 }
```

## Sample 9

- Repo: `crimx/ext-saladict`
- Raw Repo: `crimx/ext-saladict`
- SHA: `3d29f105c1288e90bd55160221a859099eed4d49`
- Type: `refactor`
- Atomic Prior: `1.0`
- Score: `59.300378`
- Utility: `91.935199`
- Files: `1`
- Hunks: `2`
- Changed Lines: `4`
- Roles: `source`
- Modules: `content`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/crimx/ext-saladict/commit/3d29f105c1288e90bd55160221a859099eed4d49

### Message

```text
refactor: remove float box max height
```

### Diff Excerpt

```diff
diff --git a/src/content/components/MenuBar/FloatBox.scss b/src/content/components/MenuBar/FloatBox.scss
index 7e50de74..bfeea164 100644
--- a/src/content/components/MenuBar/FloatBox.scss
+++ b/src/content/components/MenuBar/FloatBox.scss
@@ -1,6 +1,5 @@
 .menuBar-FloatBoxContainer {
   max-width: calc(var(--panel-width) * 0.7);
-  max-height: calc(var(--panel-height) * 0.8);
   padding: 10px;
   word-break: keep-all;
   white-space: nowrap;
@@ -16,8 +15,7 @@
 }
 
 .menuBar-FloatBox {
-  width: 100%;
-  height: 100%;
+  // max-height: calc(var(--panel-height) * 0.8);
   overflow: hidden;
 }
```

## Sample 10

- Repo: `electron/electron`
- Raw Repo: `electron/electron`
- SHA: `55a1f5d351d8b53d9734ddad5ad30088074ef5a6`
- Type: `fix`
- Atomic Prior: `1.0`
- Score: `64.596495`
- Utility: `97.950323`
- Files: `1`
- Hunks: `1`
- Changed Lines: `2`
- Roles: `source`
- Modules: `browser`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/electron/electron/commit/55a1f5d351d8b53d9734ddad5ad30088074ef5a6

### Message

```text
fix: add a hidden option to disable remote dereferencing (#14102)
```

### Diff Excerpt

```diff
diff --git a/lib/browser/objects-registry.js b/lib/browser/objects-registry.js
index 92806500dc..1956e6ec20 100644
--- a/lib/browser/objects-registry.js
+++ b/lib/browser/objects-registry.js
@@ -87,6 +87,8 @@ class ObjectsRegistry {
 
   // Private: Dereference the object from store.
   dereference (id) {
+    if (process.env.ELECTRON_DISABLE_REMOTE_DEREFERENCING) return
+
     let pointer = this.storage[id]
     if (pointer == null) {
       return
```

## Sample 11

- Repo: `erg-lang/erg`
- Raw Repo: `erg-lang/erg`
- SHA: `c17d3d147a4ffcbae37902d47d615554b8d81f4c`
- Type: `refactor`
- Atomic Prior: `1.0`
- Score: `56.941664`
- Utility: `88.513469`
- Files: `2`
- Hunks: `5`
- Changed Lines: `179`
- Roles: `source`
- Modules: `crates`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:hunk_scope_signal,pos:patch_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/erg-lang/erg/commit/c17d3d147a4ffcbae37902d47d615554b8d81f4c

### Message

```text
refactor: `Context::register_methods`
```

### Diff Excerpt

```diff
diff --git a/crates/erg_compiler/context/initialize/mod.rs b/crates/erg_compiler/context/initialize/mod.rs
index 145c3472..681b56a5 100644
--- a/crates/erg_compiler/context/initialize/mod.rs
+++ b/crates/erg_compiler/context/initialize/mod.rs
@@ -757,50 +757,19 @@ impl Context {
             };
             let name = VarName::from_str(t.local_name());
             let meta_t = v_enum(set! { val.clone() });
-            self.locals.insert(
-                name.clone(),
-                VarInfo::new(
-                    meta_t,
-                    muty,
-                    vis,
-                    Builtin,
-                    None,
-                    None,
-                    py_name.map(Str::ever),
-                    AbsLocation::unknown(),
-                ),
+            let vi = VarInfo::new(
+                meta_t,
+                muty,
+                vis,
+                Builtin,
+                None,
+                None,
+                py_name.map(Str::ever),
+                AbsLocation::unknown(),
             );
+            self.locals.insert(name.clone(), vi);
             self.consts.insert(name.clone(), val);
-            for impl_trait in ctx.super_traits.iter() {
-                if let Some(mut impls) = self.trait_impls().get_mut(&impl_trait.qual_name()) {
-                    impls.insert(TraitImpl::new(t.clone(), impl_trait.clone()));
-                } else {
... [truncated]
```

## Sample 12

- Repo: `goreleaser/goreleaser`
- Raw Repo: `goreleaser/goreleaser`
- SHA: `67e2dc60205dfb5f26e9935e6b63c40a06300180`
- Type: `refactor`
- Atomic Prior: `1.0`
- Score: `29.141436`
- Utility: `91.358074`
- Files: `2`
- Hunks: `3`
- Changed Lines: `51`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,neg:subject_compact,neg:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/goreleaser/goreleaser/commit/67e2dc60205dfb5f26e9935e6b63c40a06300180

### Message

```text
refactor: lint issues

Signed-off-by: Carlos Alexandro Becker <caarlos0@gmail.com>
```

### Diff Excerpt

```diff
diff --git a/internal/builders/golang/build_test.go b/internal/builders/golang/build_test.go
index 0ece15a5f..75e8dddcf 100644
--- a/internal/builders/golang/build_test.go
+++ b/internal/builders/golang/build_test.go
@@ -91,7 +91,7 @@ func TestWithDefaults(t *testing.T) {
 	} {
 		t.Run(name, func(t *testing.T) {
 			if testcase.build.GoBinary != "" && testcase.build.GoBinary != "go" {
-				helperCreateGoVersionExe(t, testcase.build.GoBinary, "go1.17")
+				createFakeGoBinaryWithVersion(t, testcase.build.GoBinary, "go1.17")
 			}
 			config := config.Project{
 				Builds: []config.Build{
@@ -108,27 +108,28 @@ func TestWithDefaults(t *testing.T) {
 	}
 }
 
-// helperCreateGoVersionExe creates a temporary executable with the given 'name', which will output
-// a 'go version' string with the given 'version'. The temporary directory created by this function
-// will be placed in the PATH variable for the duration of (and cleaned up at the end of) the
+// createFakeGoBinaryWithVersion creates a temporary executable with the
+// given name, which will output a go version string with the given version.
+//  The temporary directory created by this function will be placed in the PATH
+// variable for the duration of (and cleaned up at the end of) the
 // current test run.
-func helperCreateGoVersionExe(t *testing.T, name, version string) {
-	t.Helper()
-	d := t.TempDir()
-	f, err := os.Create(filepath.Join(d, name))
-	if err != nil {
-		t.Fatalf("unable to create temporary GoBinary file for testing: %v", err)
-	}
-	fmt.Fprintf(f, "#!/bin/sh\necho \"go version %s %s/%s\"\n", version, runtime.GOOS, runtime.GOARCH)
-	if err := f.Chmod(0o0755); err != nil {
-		t.Fatalf("unable to create temporary GoBinary file for testing: %v", err)
-	}
... [truncated]
```

## Sample 13

- Repo: `ibis-project/ibis`
- Raw Repo: `ibis-project/ibis`
- SHA: `6816b75cf065668d0a8b30be475ad1bf07a6081b`
- Type: `feat`
- Atomic Prior: `1.0`
- Score: `52.901617`
- Utility: `83.877463`
- Files: `2`
- Hunks: `2`
- Changed Lines: `14`
- Roles: `source,test`
- Modules: `ibis`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:module_focus_signal,pos:role_focus_signal,neg:commit_type_signal`
- Commit URL: https://github.com/ibis-project/ibis/commit/6816b75cf065668d0a8b30be475ad1bf07a6081b

### Message

```text
feat(pandas): implement radians
```

### Diff Excerpt

```diff
diff --git a/ibis/backends/pandas/execution/generic.py b/ibis/backends/pandas/execution/generic.py
index 08095a7ee..c904256a4 100644
--- a/ibis/backends/pandas/execution/generic.py
+++ b/ibis/backends/pandas/execution/generic.py
@@ -251,6 +251,11 @@ def execute_series_trig(op, data, **kwargs):
     return call_numpy_ufunc(function, op, data, **kwargs)
 
 
+@execute_node.register(ops.Radians, (pd.Series, *numeric_types))
+def execute_series_radians(_, data, **kwargs):
+    return np.radians(data)
+
+
 @execute_node.register((ops.Ceil, ops.Floor), pd.Series)
 def execute_series_ceil(op, data, **kwargs):
     return_type = np.object_ if data.dtype == np.object_ else np.int64
diff --git a/ibis/backends/tests/test_numeric.py b/ibis/backends/tests/test_numeric.py
index 1245896ba..d6a15bf55 100644
--- a/ibis/backends/tests/test_numeric.py
+++ b/ibis/backends/tests/test_numeric.py
@@ -155,14 +155,7 @@ def test_isnan_isinf(
             L(5.556).radians(),
             math.radians(5.556),
             id='radians',
-            marks=pytest.mark.notimpl(
-                [
-                    "dask",
-                    "datafusion",
-                    "impala",
-                    "pandas",
-                ]
-            ),
+            marks=pytest.mark.notimpl(["dask", "datafusion", "impala"]),
         ),
         param(
             L(5.556).degrees(),
```

## Sample 14

- Repo: `ibis-project/ibis`
- Raw Repo: `ibis-project/ibis`
- SHA: `091be3c3b6f94590922136676959d56d3efe7b75`
- Type: `feat`
- Atomic Prior: `1.0`
- Score: `52.901617`
- Utility: `83.877463`
- Files: `2`
- Hunks: `2`
- Changed Lines: `14`
- Roles: `source,test`
- Modules: `ibis`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:module_focus_signal,pos:role_focus_signal,neg:commit_type_signal`
- Commit URL: https://github.com/ibis-project/ibis/commit/091be3c3b6f94590922136676959d56d3efe7b75

### Message

```text
feat(pandas/dask): implement ops.Pi, ops.E
```

### Diff Excerpt

```diff
diff --git a/ibis/backends/pandas/execution/decimal.py b/ibis/backends/pandas/execution/decimal.py
index 022bb4b7a..e4875223f 100644
--- a/ibis/backends/pandas/execution/decimal.py
+++ b/ibis/backends/pandas/execution/decimal.py
@@ -123,3 +123,13 @@ def execute_cast_series_to_decimal(op, data, type, **kwargs):
             context.create_decimal(x).quantize(places)
         )
     )
+
+
+@execute_node.register(ops.E)
+def execute_e(op, **kwargs):
+    return np.e
+
+
+@execute_node.register(ops.Pi)
+def execute_pi(op, **kwargs):
+    return np.pi
diff --git a/ibis/backends/tests/test_numeric.py b/ibis/backends/tests/test_numeric.py
index 34ab3e32a..a302831c9 100644
--- a/ibis/backends/tests/test_numeric.py
+++ b/ibis/backends/tests/test_numeric.py
@@ -1248,9 +1248,7 @@ def test_histogram(con, alltypes):
     assert len(results.value_counts()) == n
 
 
-@pytest.mark.notimpl(
-    ["dask", "datafusion", "pandas", "polars"], raises=com.OperationNotDefinedError
-)
+@pytest.mark.notimpl(["datafusion", "polars"], raises=com.OperationNotDefinedError)
 @pytest.mark.parametrize("const", ["e", "pi"])
 def test_constants(con, const):
     expr = getattr(ibis, const)
```

## Sample 15

- Repo: `influxdata/influxdb`
- Raw Repo: `influxdata/influxdb`
- SHA: `ca5351088af148ae1e825b693df274a88bde669f`
- Type: `feat`
- Atomic Prior: `1.0`
- Score: `36.911054`
- Utility: `85.544129`
- Files: `1`
- Hunks: `1`
- Changed Lines: `12`
- Roles: `source`
- Modules: `object_store`
- Reasons: `pos:prefix_valid,pos:subject_compact,neg:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,neg:commit_type_signal`
- Commit URL: https://github.com/influxdata/influxdb/commit/ca5351088af148ae1e825b693df274a88bde669f

### Message

```text
feat: add Path->DirsAndFileName conversion

This allows for easier parsing of received paths.

Helps with #1253.
```

### Diff Excerpt

```diff
diff --git a/object_store/src/path.rs b/object_store/src/path.rs
index 7e7e7fa74c..7919b0023b 100644
--- a/object_store/src/path.rs
+++ b/object_store/src/path.rs
@@ -109,3 +109,15 @@ impl ObjectStorePath for Path {
         }
     }
 }
+
+impl From<Path> for DirsAndFileName {
+    fn from(path: Path) -> Self {
+        match path {
+            Path::AmazonS3(path) => path.into(),
+            Path::File(path) => path.into(),
+            Path::GoogleCloudStorage(path) => path.into(),
+            Path::InMemory(path) => path,
+            Path::MicrosoftAzure(path) => path.into(),
+        }
+    }
+}
```

## Sample 16

- Repo: `influxdata/influxdb`
- Raw Repo: `influxdata/influxdb`
- SHA: `55ebcf275ad0dc39ea3fd39e173a2c8f54004c50`
- Type: `refactor`
- Atomic Prior: `1.0`
- Score: `56.97217`
- Utility: `88.484851`
- Files: `2`
- Hunks: `10`
- Changed Lines: `94`
- Roles: `source`
- Modules: `ui`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/influxdata/influxdb/commit/55ebcf275ad0dc39ea3fd39e173a2c8f54004c50

### Message

```text
refactor(ui): extract helper for filtering irrelevant tokens
```

### Diff Excerpt

```diff
diff --git a/ui/src/authorizations/utils/permissions.ts b/ui/src/authorizations/utils/permissions.ts
index 2bfd3292e0..cc9c94a71e 100644
--- a/ui/src/authorizations/utils/permissions.ts
+++ b/ui/src/authorizations/utils/permissions.ts
@@ -1,8 +1,6 @@
-import {Permission, PermissionResource} from '@influxdata/influx'
+import {Permission, PermissionResource, Authorization} from '@influxdata/influx'
 import {Bucket} from 'src/types'
 
-// Types
-
 export const allAccessPermissions = (orgID: string) => [
   {
     action: Permission.ActionEnum.Read,
@@ -142,18 +140,6 @@ export const allBucketsPermissions = (
   ]
 }
 
-export const bucketPermissions = (
-  orgID: string,
-  permission: Permission.ActionEnum,
-  buckets: Bucket[]
-): Permission[] => {
-  if (!buckets) {
-    return allBucketsPermissions(orgID, permission)
-  }
-
-  return specificBucketsPermissions(buckets, permission)
-}
-
 export const selectBucket = (
   bucketName: string,
   selectedBuckets: string[]
@@ -171,3 +157,21 @@ export enum BucketTab {
   AllBuckets = 'All Buckets',
   Scoped = 'Scoped',
... [truncated]
```

## Sample 17

- Repo: `ionic-team/ionic-framework`
- Raw Repo: `ionic-team/ionic-framework`
- SHA: `90d0d33270e00dec2801678f8edf7c4b8929a137`
- Type: `test`
- Atomic Prior: `1.0`
- Score: `45.71393`
- Utility: `72.476207`
- Files: `14`
- Hunks: `12`
- Changed Lines: `388`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:role_focus_signal,pos:module_focus_signal,pos:hunk_scope_signal,neg:file_scope_signal,pos:patch_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/ionic-team/ionic-framework/commit/90d0d33270e00dec2801678f8edf7c4b8929a137

### Message

```text
test(content): add content tests to cover the different use cases
```

### Diff Excerpt

```diff
diff --git a/src/components/content/test/basic/e2e.ts b/src/components/content/test/basic/e2e.ts
new file mode 100644
index 0000000000..e69de29bb2
diff --git a/src/components/content/test/basic/index.ts b/src/components/content/test/basic/index.ts
new file mode 100644
index 0000000000..25676d6c6b
--- /dev/null
+++ b/src/components/content/test/basic/index.ts
@@ -0,0 +1,55 @@
+import {Component} from '@angular/core';
+import {ionicBootstrap} from '../../../../../src';
+
+
+@Component({
+  templateUrl: 'tabs.html'
+})
+class TabsPage {
+  page1 = E2EPage;
+  page2 = Page2;
+  page3 = Page3;
+  page4 = Page4;
+}
+
+
+@Component({
+  templateUrl: 'page4.html'
+})
+class Page4 {
+  tabsPage = TabsPage;
+}
+
+
+@Component({
+  templateUrl: 'page3.html'
+})
+class Page3 {
... [truncated]
```

## Sample 18

- Repo: `nocodb/nocodb`
- Raw Repo: `nocodb/nocodb`
- SHA: `3dafbaa0064278985c3e165aeb98ac8ac10276d4`
- Type: `feat`
- Atomic Prior: `1.0`
- Score: `46.996728`
- Utility: `77.15833`
- Files: `2`
- Hunks: `2`
- Changed Lines: `21`
- Roles: `source`
- Modules: `nc-gui,nocodb`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:patch_scope_signal,neg:commit_type_signal`
- Commit URL: https://github.com/nocodb/nocodb/commit/3dafbaa0064278985c3e165aeb98ac8ac10276d4

### Message

```text
feat: add `&` as string concatenation shortcut
```

### Diff Excerpt

```diff
diff --git a/packages/nc-gui/components/smartsheet/column/FormulaOptions.vue b/packages/nc-gui/components/smartsheet/column/FormulaOptions.vue
index 8ee16f4731..606968c569 100644
--- a/packages/nc-gui/components/smartsheet/column/FormulaOptions.vue
+++ b/packages/nc-gui/components/smartsheet/column/FormulaOptions.vue
@@ -74,7 +74,7 @@ const validators = {
 
 const availableFunctions = formulaList
 
-const availableBinOps = ['+', '-', '*', '/', '>', '<', '==', '<=', '>=', '!=']
+const availableBinOps = ['+', '-', '*', '/', '>', '<', '==', '<=', '>=', '!=', '&']
 
 const autocomplete = ref(false)
 
diff --git a/packages/nocodb/src/db/formulav2/formulaQueryBuilderv2.ts b/packages/nocodb/src/db/formulav2/formulaQueryBuilderv2.ts
index b7d1fbac65..a1eedb85a9 100644
--- a/packages/nocodb/src/db/formulav2/formulaQueryBuilderv2.ts
+++ b/packages/nocodb/src/db/formulav2/formulaQueryBuilderv2.ts
@@ -774,6 +774,25 @@ async function _formulaQueryBuilder(
       }
       return { builder: knex.raw(`??${colAlias}`, [builder || pt.name]) };
     } else if (pt.type === 'BinaryExpression') {
+
+      if(pt.operator === '&'){
+        return  fn(
+            {
+              type: 'CallExpression',
+              arguments: [
+                pt.left,
+                pt.right
+              ],
+              callee: {
+                type: 'Identifier',
+                name: 'CONCAT',
+              },
+            },
+            alias,
... [truncated]
```

## Sample 19

- Repo: `nocodb/nocodb`
- Raw Repo: `nocodb/nocodb`
- SHA: `37ab1c3ee1e659f47ca9861f730a1c9ea711ed33`
- Type: `fix`
- Atomic Prior: `1.0`
- Score: `63.804128`
- Utility: `96.685736`
- Files: `2`
- Hunks: `7`
- Changed Lines: `21`
- Roles: `source`
- Modules: `nc-gui`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/nocodb/nocodb/commit/37ab1c3ee1e659f47ca9861f730a1c9ea711ed33

### Message

```text
fix(nc-gui): Fixed issue with lookup when combined with links
```

### Diff Excerpt

```diff
diff --git a/packages/nc-gui/components/smartsheet/VirtualCell.vue b/packages/nc-gui/components/smartsheet/VirtualCell.vue
index 9b11cc2af7..58dc2da905 100644
--- a/packages/nc-gui/components/smartsheet/VirtualCell.vue
+++ b/packages/nc-gui/components/smartsheet/VirtualCell.vue
@@ -51,6 +51,8 @@ const isForm = inject(IsFormInj, ref(false))
 
 const isExpandedForm = inject(IsExpandedFormOpenInj, ref(false))
 
+const isUnderLookup = inject(IsUnderLookupInj, ref(false))
+
 function onNavigate(dir: NavigateDir, e: KeyboardEvent) {
   emit('navigate', dir)
 
@@ -99,7 +101,7 @@ onUnmounted(() => {
     @keydown.shift.enter.exact="onNavigate(NavigateDir.PREV, $event)"
   >
     <template v-if="intersected">
-      <LazyVirtualCellLinks v-if="isLink(column)" />
+      <LazyVirtualCellLinks v-if="isLink(column)" :readonly="isUnderLookup" />
       <LazyVirtualCellHasMany v-else-if="isHm(column)" />
       <LazyVirtualCellManyToMany v-else-if="isMm(column)" />
       <LazyVirtualCellBelongsTo v-else-if="isBt(column)" />
diff --git a/packages/nc-gui/components/virtual-cell/Links.vue b/packages/nc-gui/components/virtual-cell/Links.vue
index 580fba8dba..926ac07e5e 100644
--- a/packages/nc-gui/components/virtual-cell/Links.vue
+++ b/packages/nc-gui/components/virtual-cell/Links.vue
@@ -5,6 +5,10 @@ import { ref } from 'vue'
 import type { Ref } from 'vue'
 import { ActiveCellInj, CellValueInj, ColumnInj, IsUnderLookupInj, inject, useSelectedCellKeyupListener } from '#imports'
 
+const props = defineProps<{
+  readonly: boolean
+}>()
+
 const value = inject(CellValueInj, ref(0))
 
... [truncated]
```

## Sample 20

- Repo: `nocodb/nocodb`
- Raw Repo: `nocodb/nocodb`
- SHA: `e6f9f469ca4dc8123b2b19c9be57dee101855a10`
- Type: `fix`
- Atomic Prior: `1.0`
- Score: `64.596495`
- Utility: `97.950323`
- Files: `1`
- Hunks: `1`
- Changed Lines: `4`
- Roles: `source`
- Modules: `nc-gui`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/nocodb/nocodb/commit/e6f9f469ca4dc8123b2b19c9be57dee101855a10

### Message

```text
fix: duplicated variable name
```

### Diff Excerpt

```diff
diff --git a/packages/nc-gui/components/tabs/auth/user-management/ShareBase.vue b/packages/nc-gui/components/tabs/auth/user-management/ShareBase.vue
index 1e30a7e44e..d2171cbf0f 100644
--- a/packages/nc-gui/components/tabs/auth/user-management/ShareBase.vue
+++ b/packages/nc-gui/components/tabs/auth/user-management/ShareBase.vue
@@ -91,11 +91,11 @@ const recreate = async () => {
   try {
     if (!base.value.id) return
 
-    const sharedBase = await $api.base.sharedBaseCreate(base.value.id, {
+    const createdShareBase = await $api.base.sharedBaseCreate(base.value.id, {
       roles: sharedBase.value?.role || ShareBaseRole.Viewer,
     })
 
-    const newBase = sharedBase || {}
+    const newBase = createdShareBase || {}
 
     sharedBase.value = { ...newBase, role: sharedBase.value?.role }
   } catch (e: any) {
```

## Sample 21

- Repo: `nocodb/nocodb`
- Raw Repo: `nocodb/nocodb`
- SHA: `764cd102aafed686d8b6a0fcab19e86046bf0d1f`
- Type: `test`
- Atomic Prior: `1.0`
- Score: `44.009307`
- Utility: `93.43898`
- Files: `1`
- Hunks: `2`
- Changed Lines: `6`
- Roles: `source`
- Modules: `nocodb`
- Reasons: `pos:prefix_valid,pos:subject_compact,neg:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/nocodb/nocodb/commit/764cd102aafed686d8b6a0fcab19e86046bf0d1f

### Message

```text
test: clear hooks during project reset

Signed-off-by: Raju Udava <86527202+dstala@users.noreply.github.com>
```

### Diff Excerpt

```diff
diff --git a/packages/nocodb/src/models/Model.ts b/packages/nocodb/src/models/Model.ts
index 9ed0b189ca..5fa4ac4ae9 100644
--- a/packages/nocodb/src/models/Model.ts
+++ b/packages/nocodb/src/models/Model.ts
@@ -14,6 +14,7 @@ import {
 import { NcError } from '../helpers/catchError';
 import { sanitize } from '../helpers/sqlSanitize';
 import { extractProps } from '../helpers/extractProps';
+import Hook from './Hook';
 import Audit from './Audit';
 import View from './View';
 import Column from './Column';
@@ -376,6 +377,11 @@ export default class Model implements TableType {
       await view.delete(ncMeta);
     }
 
+    // delete associated hooks
+    for (const hook of await Hook.list({ fk_model_id: this.id }, ncMeta)) {
+      await Hook.delete(hook.id, ncMeta);
+    }
+
     for (const col of await this.getColumns(ncMeta)) {
       let colOptionTableName = null;
       let cacheScopeName = null;
```

## Sample 22

- Repo: `nocodb/nocodb`
- Raw Repo: `nocodb/nocodb`
- SHA: `64d57faac0dd9fcef66ae4039d84aa776273f142`
- Type: `test`
- Atomic Prior: `1.0`
- Score: `28.941265`
- Utility: `90.495484`
- Files: `1`
- Hunks: `7`
- Changed Lines: `117`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,neg:subject_compact,neg:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:hunk_scope_signal,pos:patch_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/nocodb/nocodb/commit/64d57faac0dd9fcef66ae4039d84aa776273f142

### Message

```text
test: db timezone reorg

Signed-off-by: Raju Udava <86527202+dstala@users.noreply.github.com>
```

### Diff Excerpt

```diff
diff --git a/tests/playwright/tests/db/timezone.spec.ts b/tests/playwright/tests/db/timezone.spec.ts
index 87a1976914..4919c49a8f 100644
--- a/tests/playwright/tests/db/timezone.spec.ts
+++ b/tests/playwright/tests/db/timezone.spec.ts
@@ -501,24 +501,7 @@ test.describe.serial('External DB - DateTime column', async () => {
     },
   };
 
-  // test.use({
-  //   locale: 'zh-HK',
-  //   timezoneId: 'Asia/Hong_Kong',
-  // });
-
-  test.beforeEach(async ({ page }) => {
-    context = await setup({ page, isEmptyProject: true });
-    dashboard = new DashboardPage(page, context.project);
-
-    api = new Api({
-      baseURL: `http://localhost:8080/`,
-      headers: {
-        'xc-auth': context.token,
-      },
-    });
-
-    await createTableWithDateTimeColumn(context.dbType);
-
+  async function connectToExtDb() {
     if (isPg(context)) {
       await api.base.create(context.project.id, {
         alias: 'datetimetable',
@@ -559,38 +542,60 @@ test.describe.serial('External DB - DateTime column', async () => {
     // wait for 5 seconds for the base to be created
     // hack for CI
     await dashboard.rootPage.waitForTimeout(2000);
+  }
+
... [truncated]
```

## Sample 23

- Repo: `nocodb/nocodb`
- Raw Repo: `nocodb/nocodb`
- SHA: `446400d64130d448fd32ff45231c8cb8a4513209`
- Type: `test`
- Atomic Prior: `1.0`
- Score: `44.009307`
- Utility: `93.43898`
- Files: `1`
- Hunks: `2`
- Changed Lines: `5`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,pos:subject_compact,neg:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/nocodb/nocodb/commit/446400d64130d448fd32ff45231c8cb8a4513209

### Message

```text
test: enable row delete test undo only for sqlite

Signed-off-by: Raju Udava <86527202+dstala@users.noreply.github.com>
```

### Diff Excerpt

```diff
diff --git a/tests/playwright/tests/db/undo-redo.spec.ts b/tests/playwright/tests/db/undo-redo.spec.ts
index fc1c5abdb1..52b402bf4c 100644
--- a/tests/playwright/tests/db/undo-redo.spec.ts
+++ b/tests/playwright/tests/db/undo-redo.spec.ts
@@ -5,6 +5,7 @@ import { Api, UITypes } from 'nocodb-sdk';
 import { rowMixedValue } from '../../setup/xcdb-records';
 import { GridPage } from '../../pages/Dashboard/Grid';
 import { ToolbarPage } from '../../pages/Dashboard/common/Toolbar';
+import { isSqlite } from '../../setup/db';
 
 let dashboard: DashboardPage,
   grid: GridPage,
@@ -591,6 +592,10 @@ test.describe('Undo Redo - LTAR', () => {
   });
 
   test('Row with links: Delete & Undo', async ({ page }) => {
+    // SQLite has foreign key constraint disabled by default & hence below test
+    // will work even for ext DB
+    if (!isSqlite(context)) test.skip();
+
     await dashboard.closeTab({ title: 'Team & Auth' });
     await dashboard.treeView.openTable({ title: 'Country' });
```

## Sample 24

- Repo: `openreplay/openreplay`
- Raw Repo: `openreplay/openreplay`
- SHA: `0b51a402548c9734539d196a6f49035cc1b05e96`
- Type: `feat`
- Atomic Prior: `1.0`
- Score: `53.124512`
- Utility: `85.10119`
- Files: `1`
- Hunks: `4`
- Changed Lines: `26`
- Roles: `source`
- Modules: `backend`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:hunk_scope_signal,neg:commit_type_signal`
- Commit URL: https://github.com/openreplay/openreplay/commit/0b51a402548c9734539d196a6f49035cc1b05e96

### Message

```text
feat(integrations): changed response marshaling
```

### Diff Excerpt

```diff
diff --git a/backend/services/integrations/integration/elasticsearch.go b/backend/services/integrations/integration/elasticsearch.go
index f70d3ee53..28f03a3b5 100644
--- a/backend/services/integrations/integration/elasticsearch.go
+++ b/backend/services/integrations/integration/elasticsearch.go
@@ -8,7 +8,6 @@ import (
 	"fmt"
 	elasticlib "github.com/elastic/go-elasticsearch/v7"
 	"log"
-	"reflect"
 	"strconv"
 	"time"
 
@@ -37,10 +36,9 @@ type elasticResponce struct {
 		Hits []struct {
 			Id     string          `json:"_id"`
 			Source json.RawMessage `json:"_source"`
-		}
-	}
+		} `json:"hits"`
+	} `json:"hits"`
 	ScrollId string `json:"_scroll_id"`
-	Error    map[string]interface{}
 }
 
 func (es *elasticsearch) Request(c *client) error {
@@ -57,6 +55,8 @@ func (es *elasticsearch) Request(c *client) error {
 	esC, err := elasticlib.NewClient(cfg)
 
 	if err != nil {
+		log.Println("Error while creating new ES client")
+		log.Println(err)
 		return err
 	}
 	// TODO: ping/versions/ client host check
@@ -140,15 +140,15 @@ func (es *elasticsearch) Request(c *client) error {
 	}
... [truncated]
```

## Sample 25

- Repo: `pmndrs/react-spring`
- Raw Repo: `pmndrs/react-spring`
- SHA: `2c05ec11a1ce3eb32962959e9f88f9ee23820eba`
- Type: `test`
- Atomic Prior: `1.0`
- Score: `60.471276`
- Utility: `93.176651`
- Files: `1`
- Hunks: `2`
- Changed Lines: `33`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/pmndrs/react-spring/commit/2c05ec11a1ce3eb32962959e9f88f9ee23820eba

### Message

```text
test: temporal prevention with the "delay" prop
```

### Diff Excerpt

```diff
diff --git a/packages/core/src/SpringValue.test.ts b/packages/core/src/SpringValue.test.ts
index 6b5790d3..5406a7d6 100644
--- a/packages/core/src/SpringValue.test.ts
+++ b/packages/core/src/SpringValue.test.ts
@@ -109,6 +109,7 @@ function describeProps() {
   describeImmediateProp()
   describeConfigProp()
   describeLoopProp()
+  describeDelayProp()
 }
 
 function describeToProp() {
@@ -469,6 +470,38 @@ function describeLoopProp() {
   })
 }
 
+function describeDelayProp() {
+  describe('the "delay" prop', () => {
+    beforeEach(() => jest.useFakeTimers())
+    afterEach(() => jest.useRealTimers())
+
+    // "Temporal prevention" means a delayed update can be cancelled by an
+    // earlier update. This removes the need for explicit delay cancellation.
+    it('allows the update to be temporally prevented', async () => {
+      const spring = new SpringValue(0)
+      const anim = spring.animation
+
+      spring.start(1, { config: { duration: 1000 } })
+
+      // This update will be ignored, because the next "start" call updates
+      // the "to" prop before this update's delay is finished. This update
+      // would *not* be ignored be if its "to" prop was undefined.
+      spring.start(2, { delay: 500, immediate: true })
+
+      // This update won't be affected by the previous update.
+      spring.start(0, { delay: 100, config: { duration: 1000 } })
... [truncated]
```

## Sample 26

- Repo: `pmndrs/react-three-fiber`
- Raw Repo: `pmndrs/react-three-fiber`
- SHA: `2741ebeaf3d0f7006b223c335835c4ee9b2f0bdc`
- Type: `fix`
- Atomic Prior: `1.0`
- Score: `64.596495`
- Utility: `97.950323`
- Files: `1`
- Hunks: `1`
- Changed Lines: `9`
- Roles: `source`
- Modules: `reconciler.tsx`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/pmndrs/react-three-fiber/commit/2741ebeaf3d0f7006b223c335835c4ee9b2f0bdc

### Message

```text
fix: avoid calling rAF from renderLoop if already called
```

### Diff Excerpt

```diff
diff --git a/src/reconciler.tsx b/src/reconciler.tsx
index 89584b63..e1b7181b 100644
--- a/src/reconciler.tsx
+++ b/src/reconciler.tsx
@@ -81,11 +81,12 @@ function renderLoop(timestamp: number) {
       repeat = renderGl(state, timestamp, repeat)
   })
 
-  if (repeat !== 0) return requestAnimationFrame(renderLoop)
-  else {
-    // Tail call effects, they are called when rendering stops
-    globalTailEffects.forEach((effect) => effect(timestamp))
+  if (repeat !== 0) {
+    return invalidate(false)
   }
+
+  // Tail call effects, they are called when rendering stops
+  globalTailEffects.forEach((effect) => effect(timestamp))
 }
 
 export function invalidate(state: React.MutableRefObject<CanvasContext> | boolean = true, frames: number = 2) {
```

## Sample 27

- Repo: `react-navigation/react-navigation`
- Raw Repo: `react-navigation/react-navigation`
- SHA: `bdb078a981673ca0073a325bff249c8c2f089cfd`
- Type: `fix`
- Atomic Prior: `1.0`
- Score: `64.201303`
- Utility: `97.332498`
- Files: `2`
- Hunks: `4`
- Changed Lines: `36`
- Roles: `source`
- Modules: `bottom-tabs`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:hunk_scope_signal,pos:patch_scope_signal,pos:commit_type_signal`
- Commit URL: https://github.com/react-navigation/react-navigation/commit/bdb078a981673ca0073a325bff249c8c2f089cfd

### Message

```text
fix: use react-lifecycles-compat for async mode compatibility
```

### Diff Excerpt

```diff
diff --git a/packages/bottom-tabs/src/navigators/createBottomTabNavigator.js b/packages/bottom-tabs/src/navigators/createBottomTabNavigator.js
index 9f2c952bd..e83106637 100644
--- a/packages/bottom-tabs/src/navigators/createBottomTabNavigator.js
+++ b/packages/bottom-tabs/src/navigators/createBottomTabNavigator.js
@@ -2,6 +2,7 @@
 
 import * as React from 'react';
 import { View, StyleSheet } from 'react-native';
+import { polyfill } from 'react-lifecycles-compat';
 import createTabNavigator, {
   type InjectedProps,
 } from '../utils/createTabNavigator';
@@ -18,24 +19,21 @@ type State = {
 };
 
 class TabNavigationView extends React.PureComponent<Props, State> {
+  static getDerivedStateFromProps(nextProps, prevState) {
+    const { index } = nextProps.navigation.state;
+
+    return {
+      // Set the current tab to be loaded if it was not loaded before
+      loaded: prevState.loaded.includes(index)
+        ? prevState.loaded
+        : [...prevState.loaded, index],
+    };
+  }
+
   state = {
     loaded: [this.props.navigation.state.index],
   };
 
-  componentWillReceiveProps(nextProps) {
-    if (
-      nextProps.navigation.state.index !== this.props.navigation.state.index
-    ) {
-      const { index } = nextProps.navigation.state;
... [truncated]
```

## Sample 28

- Repo: `stacks-network/stacks-core`
- Raw Repo: `stacks-network/stacks-core`
- SHA: `12676b3bb2bb66cf60cd95983fecf08124991a09`
- Type: `fix`
- Atomic Prior: `1.0`
- Score: `64.596495`
- Utility: `97.950323`
- Files: `1`
- Hunks: `1`
- Changed Lines: `2`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:commit_type_signal`
- Commit URL: https://github.com/stacks-network/stacks-core/commit/12676b3bb2bb66cf60cd95983fecf08124991a09

### Message

```text
fix: make public a test function
```

### Diff Excerpt

```diff
diff --git a/src/burnchains/tests/affirmation.rs b/src/burnchains/tests/affirmation.rs
index 1637c3dc88..ffca486fb2 100644
--- a/src/burnchains/tests/affirmation.rs
+++ b/src/burnchains/tests/affirmation.rs
@@ -140,7 +140,7 @@ fn affirmation_map_find_divergence() {
     );
 }
 
-fn make_simple_key_register(
+pub fn make_simple_key_register(
     burn_header_hash: &BurnchainHeaderHash,
     block_height: u64,
     vtxindex: u32,
```

## Sample 29

- Repo: `stacks-network/stacks-core`
- Raw Repo: `stacks-network/stacks-core`
- SHA: `ba937b71dbae9a085ddba43adc5abd1ca0c214cc`
- Type: `fix`
- Atomic Prior: `1.0`
- Score: `60.341785`
- Utility: `91.347252`
- Files: `1`
- Hunks: `20`
- Changed Lines: `101`
- Roles: `test`
- Modules: ``
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:role_focus_signal,pos:module_focus_signal,pos:patch_scope_signal,pos:commit_type_signal,pos:hunk_scope_signal`
- Commit URL: https://github.com/stacks-network/stacks-core/commit/ba937b71dbae9a085ddba43adc5abd1ca0c214cc

### Message

```text
fix: more test documentation
```

### Diff Excerpt

```diff
diff --git a/src/burnchains/tests/affirmation.rs b/src/burnchains/tests/affirmation.rs
index e7a2d7ed66..ae3ed4f4d6 100644
--- a/src/burnchains/tests/affirmation.rs
+++ b/src/burnchains/tests/affirmation.rs
@@ -169,6 +169,28 @@ fn make_simple_key_register(
     }
 }
 
+/// Create a mock reward cycle with a particular anchor block vote outcome -- it either confirms or
+/// does not confirm an anchor block.  The method returns the data for all new mocked blocks
+/// created -- it returns the list of new block headers, and for each new block, it returns the
+/// list of block-commits created (if any).  In addition, the `headers` argument will be grown to
+/// include the new block-headers (so that a succession of calls to this method will grow the given
+/// headers argument).  The list of headers returned (first tuple item) is in 1-to-1 correspondence
+/// with the list of lists of block-commits returned (second tuple item).  If the ith item in
+/// parent_commits is None, then all the block-commits in the ith list of lists of block-commits
+/// will be None.
+///
+/// The caller can control how many block-commits get produced per block with the `parent_commits`
+/// argument.  If parent_commits[i] is Some(..), then a sequence of block-commits will be produced
+/// that descend from it.
+///
+/// If `confirm_anchor_block` is true, then the prepare-phase of the reward cycle will confirm an
+/// anchor block -- there will be sufficiently many confirmations placed on a block-commit in the
+/// reward phase.  Otherwise, enough preapre-phase blocks will be missing block-commits that no
+/// anchor block is selected.
+///
+/// All block-commits produced reference the given miner key (given in the `key` argument).  All
+/// block-commits created, as well as all block headers, will be stored to the given burnchain
+/// database (in addition to being returned).
 pub fn make_reward_cycle_with_vote(
     burnchain_db: &mut BurnchainDB,
     burnchain: &Burnchain,
@@ -330,6 +352,9 @@ pub fn make_reward_cycle_with_vote(
     (new_headers, new_commits)
 }
... [truncated]
```

## Sample 30

- Repo: `ueberdosis/tiptap`
- Raw Repo: `ueberdosis/tiptap`
- SHA: `2bd17c7dc66d2d2c3131bce9e5a82326a990080c`
- Type: `feat`
- Atomic Prior: `1.0`
- Score: `53.429229`
- Utility: `85.544129`
- Files: `1`
- Hunks: `1`
- Changed Lines: `1`
- Roles: `source`
- Modules: `index.ts`
- Reasons: `pos:prefix_valid,pos:subject_compact,pos:body_compact,pos:single_focus_message,pos:clean_message,pos:not_release_like`
- Utility Reasons: `pos:file_scope_signal,pos:patch_scope_signal,pos:hunk_scope_signal,pos:role_focus_signal,pos:module_focus_signal,neg:commit_type_signal`
- Commit URL: https://github.com/ueberdosis/tiptap/commit/2bd17c7dc66d2d2c3131bce9e5a82326a990080c

### Message

```text
feat: export isList, fix #1326
```

### Diff Excerpt

```diff
diff --git a/packages/core/src/index.ts b/packages/core/src/index.ts
index d42201c5f..2a8eb0dbe 100644
--- a/packages/core/src/index.ts
+++ b/packages/core/src/index.ts
@@ -29,6 +29,7 @@ export { default as getMarksBetween } from './helpers/getMarksBetween'
 export { default as getNodeAttributes } from './helpers/getNodeAttributes'
 export { default as getNodeType } from './helpers/getNodeType'
 export { default as isActive } from './helpers/isActive'
+export { default as isList } from './helpers/isList'
 export { default as isMarkActive } from './helpers/isMarkActive'
 export { default as isNodeActive } from './helpers/isNodeActive'
 export { default as isNodeEmpty } from './helpers/isNodeEmpty'
```
